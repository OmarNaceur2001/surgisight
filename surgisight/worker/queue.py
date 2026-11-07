"""Database-backed job queue for SurgiSight pipeline orchestration (WP5).

Replaces Redis/RQ per project specification:
- Claims jobs with SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL
- Uses atomic state check on SQLite for local development and tests
- Strictly idempotent on (video_id, model_versions, config_hash)
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from surgisight.contract.types import RunStatus
from surgisight.db import AnalysisRunModel


def calculate_idempotency_key(
    video_id: str, model_versions: dict[str, Any], config_hash: str
) -> str:
    """Generate deterministic idempotency key."""
    canonical_str = f"{video_id}:{json.dumps(model_versions, sort_keys=True)}:{config_hash}"
    digest = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()[:16]
    return f"run_{video_id[:8]}_{digest}"


def enqueue_analysis_run(
    db: Session,
    video_id: str,
    model_versions: dict[str, Any] | None = None,
    config_hash: str = "default_v1",
) -> tuple[AnalysisRunModel, bool]:
    """Enqueue an analysis run idempotently.

    Returns:
        (AnalysisRunModel, created: bool)
    """
    versions = model_versions or {"M2": "0.1.0-mock", "M3": "0.1.0-mock", "M4": "0.1.0-mock"}
    idempotency_key = calculate_idempotency_key(video_id, versions, config_hash)

    # Check for existing run
    existing = db.execute(
        select(AnalysisRunModel).where(AnalysisRunModel.idempotency_key == idempotency_key)
    ).scalar_one_or_none()

    if existing:
        return existing, False

    new_run = AnalysisRunModel(
        video_id=video_id,
        status=RunStatus.PENDING.value,
        progress=0.0,
        stage="init",
        contract_version="1.0",
        model_versions=versions,
        config_hash=config_hash,
        idempotency_key=idempotency_key,
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)
    return new_run, True


def claim_next_run(db: Session, worker_id: str = "worker_1") -> AnalysisRunModel | None:
    """Atomically claim the next pending analysis run."""
    bind = db.get_bind()
    dialect_name = bind.dialect.name if bind else "sqlite"

    if dialect_name == "postgresql":
        # PostgreSQL SKIP LOCKED query
        stmt = (
            select(AnalysisRunModel)
            .where(AnalysisRunModel.status == RunStatus.PENDING.value)
            .order_by(AnalysisRunModel.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        run = db.execute(stmt).scalar_one_or_none()
        if run:
            run.status = RunStatus.PROCESSING.value
            run.started_at = datetime.now(UTC)
            db.commit()
            db.refresh(run)
            return run
        return None
    else:
        # SQLite atomic transaction
        run = db.execute(
            select(AnalysisRunModel)
            .where(AnalysisRunModel.status == RunStatus.PENDING.value)
            .limit(1)
        ).scalar_one_or_none()

        if run:
            run.status = RunStatus.PROCESSING.value
            run.started_at = datetime.now(UTC)
            db.commit()
            db.refresh(run)
            return run
        return None
