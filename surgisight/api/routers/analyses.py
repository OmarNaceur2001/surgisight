"""Analysis, report, correction, and review REST API (WP9)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

import pyarrow.parquet as pq
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from surgisight.analytics.lexicon import validate_text_lexicon
from surgisight.api.deps import get_current_user, record_access_log, require_roles
from surgisight.contract.models import Report
from surgisight.contract.types import ReportStatus, RunStatus, TargetType, UserRole
from surgisight.db import (
    AnalysisRunModel,
    CorrectionModel,
    EventModel,
    PhaseSegmentModel,
    ReportModel,
    ToolIntervalModel,
    TripletIndexModel,
    UserModel,
    VideoModel,
    get_db,
)
from surgisight.report.pdf import ReportLabPdfRenderer
from surgisight.worker.queue import enqueue_analysis_run
from surgisight.worker.storage import get_run_storage_dir

router = APIRouter(tags=["analyses", "reports"])


class AnalysisCreateRequest(BaseModel):
    """Optional run configuration fingerprint; no arbitrary model configuration accepted."""

    config_hash: str = Field(default="default_v1", min_length=1, max_length=64)


class AnalysisCreateResponse(BaseModel):
    id: str
    video_id: str
    status: str
    progress: float
    stage: str
    created: bool


class AnalysisResponse(BaseModel):
    id: str
    video_id: str
    status: str
    progress: float
    stage: str
    contract_version: str
    model_versions: dict[str, str]
    started_at: str | None
    finished_at: str | None
    report_id: str | None


class PredictionPage(BaseModel):
    stream: str
    count: int
    rows: list[dict[str, object]]


class CorrectionRequest(BaseModel):
    target_type: TargetType
    target_ref: str = Field(min_length=1, max_length=128)
    before: dict
    after: dict
    reason: str = Field(min_length=3, max_length=4000)


class CorrectionResponse(BaseModel):
    id: str
    report_id: str
    author_id: str
    target_type: str
    target_ref: str
    before: dict
    after: dict
    reason: str
    created_at: str


class ReviewRequest(BaseModel):
    status: Literal["REVIEWED"] = "REVIEWED"


def _get_run(db: Session, run_id: str) -> AnalysisRunModel:
    run = db.execute(select(AnalysisRunModel).where(AnalysisRunModel.id == run_id)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    return run


def _get_report(db: Session, report_id: str) -> ReportModel:
    row = db.execute(select(ReportModel).where(ReportModel.id == report_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return row


@router.post(
    "/videos/{video_id}/analyses",
    response_model=AnalysisCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_analysis(
    video_id: str,
    body: AnalysisCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(require_roles(UserRole.RESEARCHER, UserRole.REVIEWER))],
) -> AnalysisCreateResponse:
    """Queue an analysis using the existing idempotent database-backed worker."""
    video = db.execute(select(VideoModel).where(VideoModel.id == video_id)).scalar_one_or_none()
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    run, created = enqueue_analysis_run(db, video_id, config_hash=body.config_hash)
    record_access_log(db, action="queue_analysis" if created else "reuse_analysis_run",
                      user_id=user.id, video_id=video_id)
    return AnalysisCreateResponse(
        id=run.id, video_id=run.video_id, status=run.status, progress=run.progress,
        stage=run.stage, created=created,
    )


@router.get("/analyses/{run_id}", response_model=AnalysisResponse)
def get_analysis(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
) -> AnalysisResponse:
    """Read run state and linked report identifier."""
    run = _get_run(db, run_id)
    record_access_log(db, action="read_analysis", user_id=user.id, video_id=run.video_id)
    report = db.execute(select(ReportModel).where(ReportModel.run_id == run.id)).scalar_one_or_none()
    return AnalysisResponse(
        id=run.id, video_id=run.video_id, status=run.status, progress=run.progress,
        stage=run.stage, contract_version=run.contract_version,
        model_versions={str(k): str(v) for k, v in run.model_versions.items()},
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        report_id=report.id if report else None,
    )


@router.get("/analyses/{run_id}/predictions", response_model=PredictionPage)
def get_predictions(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
    stream: Literal["1hz", "5hz"] = "1hz",
    from_s: Annotated[float | None, Query(alias="from", ge=0)] = None,
    to_s: Annotated[float | None, Query(alias="to", gt=0)] = None,
    limit: int = Query(default=2000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
) -> PredictionPage:
    """Return stored Parquet columns for a time slice; does not synthesize omitted fields."""
    run = _get_run(db, run_id)
    if run.status != RunStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="Predictions are available after the run completes.")
    path = get_run_storage_dir(run_id) / f"predictions_{stream}.parquet"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Prediction stream '{stream}' is not available.")
    table = pq.read_table(path)
    if from_s is not None:
        import pyarrow.compute as pc
        table = table.filter(pc.greater_equal(table["t"], from_s))
    if to_s is not None:
        import pyarrow.compute as pc
        table = table.filter(pc.less(table["t"], to_s))
    rows = table.slice(offset, limit).to_pylist()
    record_access_log(db, action=f"read_predictions_{stream}", user_id=user.id, video_id=run.video_id)
    return PredictionPage(stream=stream, count=len(rows), rows=rows)


@router.get("/reports/{report_id}")
def get_report(
    report_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
) -> dict:
    """Return the canonical validated report JSON."""
    row = _get_report(db, report_id)
    report = Report.model_validate(row.report_json)
    run = _get_run(db, row.run_id)
    record_access_log(db, action="read_report_json", user_id=user.id, video_id=run.video_id)
    return report.model_dump(mode="json")


@router.get("/reports/{report_id}/pdf")
def get_report_pdf(
    report_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
) -> Response:
    """Render PDF from persisted report JSON on demand; never accepts a separate PDF payload."""
    row = _get_report(db, report_id)
    report = Report.model_validate(row.report_json)
    run = _get_run(db, row.run_id)
    pdf_bytes = ReportLabPdfRenderer().render_pdf(report)
    record_access_log(db, action="export_report_pdf", user_id=user.id, video_id=run.video_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="surgisight-report-{report_id}.pdf"',
                 "X-Research-Notice": report.disclaimer},
    )


@router.post(
    "/reports/{report_id}/corrections",
    response_model=CorrectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_report_correction(
    report_id: str,
    body: CorrectionRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(require_roles(UserRole.RESEARCHER, UserRole.REVIEWER))],
) -> CorrectionResponse:
    """Append a correction proposal; existing correction rows are never mutated."""
    row = _get_report(db, report_id)
    try:
        validate_text_lexicon(body.reason, context="correction reason")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    correction = CorrectionModel(
        id=str(uuid4()), report_id=row.id, author_id=user.id,
        target_type=body.target_type.value, target_ref=body.target_ref,
        before=body.before, after=body.after, reason=body.reason,
    )
    db.add(correction)
    db.commit()
    db.refresh(correction)
    run = _get_run(db, row.run_id)
    record_access_log(db, action="propose_report_correction", user_id=user.id, video_id=run.video_id)
    return CorrectionResponse(
        id=correction.id, report_id=correction.report_id, author_id=correction.author_id,
        target_type=correction.target_type, target_ref=correction.target_ref,
        before=correction.before, after=correction.after, reason=correction.reason,
        created_at=correction.created_at.isoformat(),
    )


@router.post("/reports/{report_id}/review")
def review_report(
    report_id: str,
    body: ReviewRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(require_roles(UserRole.REVIEWER))],
) -> dict:
    """Reviewer-only lifecycle transition to REVIEWED; the report remains append-only history."""
    row = _get_report(db, report_id)
    report = Report.model_validate(row.report_json)
    if report.status != ReportStatus.DRAFT_PENDING_REVIEW:
        raise HTTPException(status_code=409, detail="Only draft reports can be reviewed.")
    reviewed = report.model_copy(update={"status": ReportStatus.REVIEWED})
    row.report_json = json.loads(reviewed.model_dump_json())
    row.status = ReportStatus.REVIEWED.value
    row.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    run = _get_run(db, row.run_id)
    record_access_log(db, action="review_report", user_id=user.id, video_id=run.video_id)
    return {"id": row.id, "status": row.status, "disclaimer": reviewed.disclaimer}


@router.get("/videos")
def list_videos(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
    phase: str | None = None,
    tool: str | None = None,
    triplet: int | None = None,
    event: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Search the library by indexed analysis metadata with bounded pagination."""
    stmt = select(VideoModel).distinct().join(AnalysisRunModel)
    if phase:
        stmt = stmt.join(PhaseSegmentModel, PhaseSegmentModel.run_id == AnalysisRunModel.id).where(
            PhaseSegmentModel.label == phase
        )
    if tool:
        stmt = stmt.join(ToolIntervalModel, ToolIntervalModel.run_id == AnalysisRunModel.id).where(
            ToolIntervalModel.tool == tool
        )
    if triplet is not None:
        stmt = stmt.join(TripletIndexModel, TripletIndexModel.run_id == AnalysisRunModel.id).where(
            TripletIndexModel.ivt_id == triplet
        )
    if event:
        stmt = stmt.join(EventModel, EventModel.run_id == AnalysisRunModel.id).where(
            EventModel.type == event
        )
    videos = db.execute(stmt.order_by(VideoModel.created_at.desc()).offset(offset).limit(limit)).scalars().all()
    record_access_log(db, action="search_video_library", user_id=user.id)
    return {
        "items": [
            {"id": v.id, "global_video_id": v.global_video_id, "dataset": v.dataset,
             "duration_s": v.duration_s, "fps": v.fps, "created_at": v.created_at.isoformat(),
             "disclaimer": "Research prototype — not for clinical use"}
            for v in videos
        ],
        "limit": limit, "offset": offset,
    }
