"""Aggregated cohort reference statistics API (WP11)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from surgisight.api.deps import get_current_user, record_access_log
from surgisight.db import CohortStatsModel, UserModel, get_db

router = APIRouter(prefix="/cohort", tags=["cohort"])


class CohortStatistic(BaseModel):
    """One aggregate statistic without subject-level ranking."""
    version: str
    phase: str | None
    statistic: str
    value: float
    n_videos: int


class CohortResponse(BaseModel):
    """Aggregated reference statistics."""
    items: list[CohortStatistic]
    notice: str = "Aggregated research reference statistics; not a surgeon rating."


@router.get("/stats", response_model=CohortResponse)
def get_cohort_statistics(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
    version: Annotated[str | None, Query(max_length=32)] = None,
    phase: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
) -> CohortResponse:
    """Return only aggregated cohort statistics; no user-level scores are exposed."""
    stmt = select(CohortStatsModel)
    if version:
        stmt = stmt.where(CohortStatsModel.version == version)
    if phase:
        stmt = stmt.where(CohortStatsModel.phase == phase.upper())
    rows = db.execute(stmt.order_by(CohortStatsModel.version, CohortStatsModel.phase)).scalars().all()
    record_access_log(db, action="read_cohort_statistics", user_id=user.id)
    return CohortResponse(
        items=[
            CohortStatistic(
                version=row.version,
                phase=row.phase,
                statistic=row.statistic,
                value=row.value,
                n_videos=row.n_videos,
            )
            for row in rows
        ]
    )
