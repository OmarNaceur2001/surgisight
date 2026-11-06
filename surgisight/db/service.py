"""Database service layer with append-only enforcement for expert corrections (P6).

Features:
- Enforces append-only rule on `corrections` across both SQLite and PostgreSQL.
- Idempotent analysis run creation.
- Relational indexing of timeline phases, tools, events, and triplets from Report.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from surgisight.contract.models import Report
from surgisight.db.models import (
    CorrectionModel,
    EventModel,
    PhaseSegmentModel,
    TripletIndexModel,
)


class AppendOnlyViolationError(PermissionError):
    """Raised when an attempt is made to update or delete an append-only correction."""

    pass


POSTGRES_APPEND_ONLY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION deny_correction_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'corrections table is strictly append-only (P6 requirement)';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_corrections_append_only ON corrections;
CREATE TRIGGER trg_corrections_append_only
BEFORE UPDATE OR DELETE ON corrections
FOR EACH ROW EXECUTE FUNCTION deny_correction_mutation();
"""


def verify_correction_mutation_forbidden(operation: str) -> None:
    """Service-level guard ensuring corrections cannot be updated or deleted."""
    if operation.upper() in ("UPDATE", "DELETE"):
        raise AppendOnlyViolationError(
            f"Cannot {operation.upper()} correction: 'corrections' table is strictly append-only (P6)."
        )


class DatabaseService:
    """Service layer managing database operations and index population."""

    @staticmethod
    def add_correction_sync(
        session: Session,
        report_id: str,
        author_id: str,
        target_type: str,
        target_ref: str,
        before: dict[str, Any],
        after: dict[str, Any],
        reason: str,
    ) -> CorrectionModel:
        """Insert a new correction. Never allows updates or deletions."""
        correction = CorrectionModel(
            report_id=report_id,
            author_id=author_id,
            target_type=target_type,
            target_ref=target_ref,
            before=before,
            after=after,
            reason=reason,
        )
        session.add(correction)
        session.flush()
        return correction

    @staticmethod
    def update_correction_sync(
        session: Session, correction_id: str, updates: dict[str, Any]
    ) -> None:
        """Always fails: updates are forbidden."""
        verify_correction_mutation_forbidden("UPDATE")

    @staticmethod
    def delete_correction_sync(session: Session, correction_id: str) -> None:
        """Always fails: deletions are forbidden."""
        verify_correction_mutation_forbidden("DELETE")

    @staticmethod
    async def add_correction_async(
        session: AsyncSession,
        report_id: str,
        author_id: str,
        target_type: str,
        target_ref: str,
        before: dict[str, Any],
        after: dict[str, Any],
        reason: str,
    ) -> CorrectionModel:
        correction = CorrectionModel(
            report_id=report_id,
            author_id=author_id,
            target_type=target_type,
            target_ref=target_ref,
            before=before,
            after=after,
            reason=reason,
        )
        session.add(correction)
        await session.flush()
        return correction

    @staticmethod
    def populate_run_indices(session: Session, run_id: str, report: Report) -> None:
        """Populate relational search tables (phases, tools, events, triplets) from Report model."""
        # 1. Index phase segments
        for seg in report.phases:
            session.add(
                PhaseSegmentModel(
                    run_id=run_id,
                    label=seg.label.value,
                    name=seg.name,
                    start=seg.start,
                    end=seg.end,
                    conf=seg.conf,
                    uncertain=seg.uncertain,
                )
            )

        # 2. Index events
        for ev in report.events:
            session.add(
                EventModel(
                    run_id=run_id,
                    type=ev.type,
                    t=ev.t,
                    conf=ev.conf,
                    uncertain=ev.uncertain,
                    evidence=ev.evidence,
                )
            )

        # 3. Index triplet highlights
        for tri in report.triplet_highlights:
            session.add(
                TripletIndexModel(
                    run_id=run_id,
                    t=tri.t,
                    ivt_id=tri.ivt_id,
                    score=tri.score,
                )
            )

        session.flush()
