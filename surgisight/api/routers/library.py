"""Filtered, paginated video library endpoint (WP9)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from surgisight.api.deps import get_current_user, record_access_log
from surgisight.db import (
    AnalysisRunModel, EventModel, PhaseSegmentModel, TripletIndexModel,
    ToolIntervalModel, UserModel, VideoModel, get_db
)

router = APIRouter(prefix="/videos", tags=["videos"])


class LibraryVideo(BaseModel):
    """Compact list item for the review dashboard."""
    id: str
    global_video_id: str
    dataset: str
    duration_s: float
    fps: float
    created_at: str
    latest_run_id: str | None = None
    latest_run_status: str | None = None
    report_id: str | None = None
    notice: str = "Research prototype — not for clinical use"


class LibraryResponse(BaseModel):
    """Paged library response."""
    items: list[LibraryVideo]
    limit: int
    offset: int
    total: int


@router.get("", response_model=LibraryResponse)
def list_videos(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
    phase: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    tool: Annotated[str | None, Query(min_length=2, max_length=32)] = None,
    triplet: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    event: Annotated[str | None, Query(min_length=2, max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LibraryResponse:
    """Search by indexed phase, tool, triplet name/id, or event type."""
    stmt = select(VideoModel)
    if phase:
        stmt = stmt.where(exists(
            select(1).select_from(PhaseSegmentModel)
            .join(AnalysisRunModel, PhaseSegmentModel.run_id == AnalysisRunModel.id)
            .where(AnalysisRunModel.video_id == VideoModel.id, PhaseSegmentModel.label == phase.upper())
        ))
    if tool:
        stmt = stmt.where(exists(
            select(1).select_from(ToolIntervalModel)
            .join(AnalysisRunModel, ToolIntervalModel.run_id == AnalysisRunModel.id)
            .where(AnalysisRunModel.video_id == VideoModel.id, ToolIntervalModel.tool.ilike(tool))
        ))
    if triplet:
        stmt = stmt.where(exists(
            select(1).select_from(TripletIndexModel)
            .join(AnalysisRunModel, TripletIndexModel.run_id == AnalysisRunModel.id)
            .where(
                AnalysisRunModel.video_id == VideoModel.id,
                (TripletIndexModel.ivt_name.ilike(f"%{triplet}%"))
                | (TripletIndexModel.ivt_id.cast(str) == triplet),
            )
        ))
    if event:
        stmt = stmt.where(exists(
            select(1).select_from(EventModel)
            .join(AnalysisRunModel, EventModel.run_id == AnalysisRunModel.id)
            .where(AnalysisRunModel.video_id == VideoModel.id, EventModel.type.ilike(f"%{event}%"))
        ))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    videos = db.execute(stmt.order_by(VideoModel.created_at.desc()).offset(offset).limit(limit)).scalars().all()
    items: list[LibraryVideo] = []
    for video in videos:
        latest = db.execute(
            select(AnalysisRunModel).where(AnalysisRunModel.video_id == video.id)
            .order_by(AnalysisRunModel.started_at.desc().nullslast()).limit(1)
        ).scalar_one_or_none()
        items.append(LibraryVideo(
            id=video.id, global_video_id=video.global_video_id, dataset=video.dataset,
            duration_s=video.duration_s, fps=video.fps, created_at=video.created_at.isoformat(),
            latest_run_id=latest.id if latest else None,
            latest_run_status=latest.status if latest else None,
            report_id=latest.report.id if latest and latest.report else None,
        ))
    record_access_log(db, action="list_videos", user_id=user.id)
    return LibraryResponse(items=items, limit=limit, offset=offset, total=total)
