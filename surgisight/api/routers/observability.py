"""Latency metrics API; exposes aggregates only, without sample identifiers."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from surgisight.analytics.latency import LATENCY_METRICS
from surgisight.api.deps import get_current_user, record_access_log
from surgisight.db import UserModel, get_db

router = APIRouter(prefix="/metrics", tags=["observability"])


@router.get("/latency")
def get_latency_metrics(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
) -> dict[str, object]:
    """Return in-process p50/p95 replay and online-step measurements."""
    record_access_log(db, action="read_latency_metrics", user_id=user.id)
    return {
        "stages": LATENCY_METRICS.snapshot(),
        "scope": "current API process only; metrics reset on process restart",
        "notice": "Measured local processing samples; not an end-to-end service-level guarantee.",
    }
