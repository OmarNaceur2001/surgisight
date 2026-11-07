"""Analysis-run creation, status, and Parquet prediction APIs (WP9)."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from surgisight.api.deps import get_current_user, record_access_log, require_roles
from surgisight.contract.types import UserRole
from surgisight.db import AnalysisRunModel, UserModel, VideoModel, get_db
from surgisight.worker.queue import enqueue_analysis_run
from surgisight.worker.storage import read_predictions_parquet

create_router = APIRouter(prefix="/videos", tags=["analyses"])
router = APIRouter(prefix="/analyses", tags=["analyses"])


class CreateAnalysisRequest(BaseModel):
    """Idempotent analysis submission request."""
    model_versions: dict[str, str] = Field(default_factory=lambda: {"M2": "mock", "M3": "mock", "M4": "mock"})
    config_hash: str = Field(default="default_v1", min_length=1, max_length=64)


class AnalysisRunResponse(BaseModel):
    """Public analysis status without local storage paths."""
    id: str
    video_id: str
    status: str
    progress: float
    stage: str
    contract_version: str
    model_versions: dict[str, str]
    config_hash: str
    started_at: str | None = None
    finished_at: str | None = None
    report_id: str | None = None
    error: str | None = None
    notice: str = "Research prototype — not for clinical use"


class PredictionSliceResponse(BaseModel):
    """Bounded prediction slice."""
    run_id: str
    stream: Literal["1hz", "5hz"]
    offset: int
    limit: int
    total: int
    records: list[dict]


def _run_response(run: AnalysisRunModel) -> AnalysisRunResponse:
    report_id = run.report.id if run.report is not None else None
    return AnalysisRunResponse(
        id=run.id, video_id=run.video_id, status=run.status, progress=run.progress,
        stage=run.stage, contract_version=run.contract_version, model_versions=run.model_versions,
        config_hash=run.config_hash,
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        report_id=report_id, error=run.error,
    )


@create_router.post("/{video_id}/analyses", response_model=AnalysisRunResponse, status_code=202)
def create_analysis(
    video_id: str,
    payload: CreateAnalysisRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(require_roles(UserRole.RESEARCHER))],
) -> AnalysisRunResponse:
    """Enqueue an analysis idempotently."""
    video = db.execute(select(VideoModel).where(VideoModel.id == video_id)).scalar_one_or_none()
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    run, created = enqueue_analysis_run(
        db, video_id=video_id, model_versions=payload.model_versions, config_hash=payload.config_hash
    )
    record_access_log(db, action="create_analysis" if created else "reuse_analysis",
                      user_id=user.id, video_id=video_id)
    db.refresh(run)
    return _run_response(run)


@router.get("/{analysis_id}", response_model=AnalysisRunResponse)
def get_analysis(
    analysis_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
) -> AnalysisRunResponse:
    """Read one analysis status."""
    run = db.execute(select(AnalysisRunModel).where(AnalysisRunModel.id == analysis_id)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    record_access_log(db, action="read_analysis", user_id=user.id, video_id=run.video_id)
    return _run_response(run)


@router.get("/{analysis_id}/predictions", response_model=PredictionSliceResponse)
def get_predictions(
    analysis_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
    stream: Literal["1hz", "5hz"] = "1hz",
    from_s: Annotated[float | None, Query(alias="from", ge=0)] = None,
    to_s: Annotated[float | None, Query(alias="to", ge=0)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=5400)] = 1000,
) -> PredictionSliceResponse:
    """Return a bounded time-windowed Parquet slice."""
    if from_s is not None and to_s is not None and to_s < from_s:
        raise HTTPException(status_code=422, detail="'to' must be greater than or equal to 'from'")
    run = db.execute(select(AnalysisRunModel).where(AnalysisRunModel.id == analysis_id)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    try:
        rows = read_predictions_parquet(analysis_id, stream=stream).to_pylist()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Predictions are not available yet") from exc
    if from_s is not None:
        rows = [row for row in rows if float(row["t"]) >= from_s]
    if to_s is not None:
        rows = [row for row in rows if float(row["t"]) <= to_s]
    total = len(rows)
    records = rows[offset:offset + limit]
    record_access_log(db, action=f"read_predictions_{stream}", user_id=user.id, video_id=run.video_id)
    return PredictionSliceResponse(run_id=analysis_id, stream=stream, offset=offset,
                                   limit=limit, total=total, records=records)
