"""Report JSON/PDF, append-only corrections, and review lifecycle (WP9)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from surgisight.analytics.lexicon import validate_object_lexicon
from surgisight.api.deps import get_current_user, record_access_log, require_roles
from surgisight.contract.models import Report
from surgisight.contract.types import ReportStatus, TargetType, UserRole
from surgisight.db import CorrectionModel, ReportModel, UserModel, get_db
from surgisight.report.pdf import ReportLabPdfRenderer

router = APIRouter(prefix="/reports", tags=["reports"])


class CorrectionRequest(BaseModel):
    """Immutable correction proposal."""
    target_type: TargetType
    target_ref: str = Field(min_length=1, max_length=128)
    before: dict
    after: dict
    reason: str = Field(min_length=3, max_length=2000)


class CorrectionResponse(BaseModel):
    """Correction response."""
    id: str
    report_id: str
    author_id: str
    target_type: str
    target_ref: str
    before: dict
    after: dict
    reason: str
    created_at: str


class ReviewResponse(BaseModel):
    """Report review transition receipt."""
    report_id: str
    status: str
    reviewed_at: str
    notice: str = "Research prototype — not for clinical use"


def _get_report(db: Session, report_id: str) -> ReportModel:
    row = db.execute(select(ReportModel).where(ReportModel.id == report_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return row


def _correction_response(row: CorrectionModel) -> CorrectionResponse:
    return CorrectionResponse(
        id=row.id, report_id=row.report_id, author_id=row.author_id,
        target_type=row.target_type, target_ref=row.target_ref, before=row.before,
        after=row.after, reason=row.reason, created_at=row.created_at.isoformat(),
    )


@router.get("/{report_id}")
def get_report(
    report_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
) -> dict:
    """Return validated report JSON; the same JSON powers the PDF."""
    row = _get_report(db, report_id)
    report = Report.model_validate(row.report_json)
    record_access_log(db, action="read_report", user_id=user.id)
    return report.model_dump(mode="json")


@router.get("/{report_id}/pdf")
def download_report_pdf(
    report_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
) -> Response:
    """Render PDF only from the validated stored report JSON."""
    row = _get_report(db, report_id)
    report = Report.model_validate(row.report_json)
    content = ReportLabPdfRenderer().render_pdf(report)
    record_access_log(db, action="download_report_pdf", user_id=user.id)
    return Response(content=content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="surgisight-report-{report_id}.pdf"'})


@router.get("/{report_id}/corrections", response_model=list[CorrectionResponse])
def list_corrections(
    report_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
) -> list[CorrectionResponse]:
    """Return immutable correction history."""
    _get_report(db, report_id)
    rows = db.execute(select(CorrectionModel).where(CorrectionModel.report_id == report_id)
                      .order_by(CorrectionModel.created_at.asc())).scalars().all()
    record_access_log(db, action="read_report_corrections", user_id=user.id)
    return [_correction_response(row) for row in rows]


@router.post("/{report_id}/corrections", response_model=CorrectionResponse, status_code=201)
def add_correction(
    report_id: str,
    payload: CorrectionRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(require_roles(UserRole.RESEARCHER, UserRole.REVIEWER))],
) -> CorrectionResponse:
    """Append a proposed correction without mutating source report JSON."""
    report_row = _get_report(db, report_id)
    if report_row.status == ReportStatus.REVIEWED.value:
        raise HTTPException(status_code=409, detail="Reviewed reports are read-only")
    validate_object_lexicon({"reason": payload.reason, "before": payload.before, "after": payload.after},
                            path="correction")
    row = CorrectionModel(
        report_id=report_id, author_id=user.id, target_type=payload.target_type.value,
        target_ref=payload.target_ref, before=payload.before, after=payload.after, reason=payload.reason,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    record_access_log(db, action="propose_report_correction", user_id=user.id)
    return _correction_response(row)


@router.post("/{report_id}/review", response_model=ReviewResponse)
def review_report(
    report_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(require_roles(UserRole.REVIEWER))],
) -> ReviewResponse:
    """Promote a report to REVIEWED, only for reviewer/admin roles."""
    row = _get_report(db, report_id)
    if row.status == ReportStatus.REVIEWED.value:
        raise HTTPException(status_code=409, detail="Report has already been reviewed")
    report = Report.model_validate(row.report_json)
    updated = report.model_copy(update={"status": ReportStatus.REVIEWED})
    row.status = ReportStatus.REVIEWED.value
    row.report_json = updated.model_dump(mode="json")
    db.commit()
    reviewed_at = datetime.now(UTC).isoformat()
    record_access_log(db, action=f"review_report:{reviewed_at}", user_id=user.id)
    return ReviewResponse(report_id=report_id, status=row.status, reviewed_at=reviewed_at)
