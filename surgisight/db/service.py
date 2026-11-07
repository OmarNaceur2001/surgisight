"""Database service with append-only corrections and report indexing."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from surgisight.contract.models import Report
from surgisight.db.models import (
    CorrectionModel, EventModel, PhaseSegmentModel, ToolIntervalModel, TripletIndexModel
)


class AppendOnlyViolationError(PermissionError):
    """Raised when a correction mutation is attempted."""


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
    """Reject updates and deletes to the append-only correction stream."""
    if operation.upper() in {"UPDATE", "DELETE"}:
        raise AppendOnlyViolationError(f"Cannot {operation.upper()} append-only correction.")


class DatabaseService:
    """Database operations which are portable across SQLite and PostgreSQL."""

    @staticmethod
    def add_correction_sync(
        session: Session, report_id: str, author_id: str, target_type: str,
        target_ref: str, before: dict[str, Any], after: dict[str, Any], reason: str
    ) -> CorrectionModel:
        """Append one correction proposal."""
        row = CorrectionModel(
            report_id=report_id, author_id=author_id, target_type=target_type,
            target_ref=target_ref, before=before, after=after, reason=reason
        )
        session.add(row)
        session.flush()
        return row

    @staticmethod
    def update_correction_sync(session: Session, correction_id: str, updates: dict[str, Any]) -> None:
        """Always reject correction updates."""
        verify_correction_mutation_forbidden("UPDATE")

    @staticmethod
    def delete_correction_sync(session: Session, correction_id: str) -> None:
        """Always reject correction deletion."""
        verify_correction_mutation_forbidden("DELETE")

    @staticmethod
    async def add_correction_async(
        session: AsyncSession, report_id: str, author_id: str, target_type: str,
        target_ref: str, before: dict[str, Any], after: dict[str, Any], reason: str
    ) -> CorrectionModel:
        """Append one correction proposal asynchronously."""
        row = CorrectionModel(
            report_id=report_id, author_id=author_id, target_type=target_type,
            target_ref=target_ref, before=before, after=after, reason=reason
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    def populate_run_indices(session: Session, run_id: str, report: Report) -> None:
        """Populate relational search indexes from the validated report JSON."""
        for seg in report.phases:
            session.add(PhaseSegmentModel(
                run_id=run_id, label=seg.label.value, name=seg.name, start=seg.start,
                end=seg.end, conf=seg.conf, uncertain=seg.uncertain
            ))
        for tool in report.tools:
            if tool.usage_s > 0:
                session.add(ToolIntervalModel(
                    run_id=run_id, tool=tool.tool.value, start=0.0, end=tool.usage_s
                ))
        for event in report.events:
            session.add(EventModel(
                run_id=run_id, type=event.type, t=event.t, conf=event.conf,
                uncertain=event.uncertain, evidence=event.evidence
            ))
        for triplet in report.triplet_highlights:
            session.add(TripletIndexModel(
                run_id=run_id, t=triplet.t, ivt_id=triplet.ivt_id,
                ivt_name=triplet.ivt_name, score=triplet.score
            ))
        session.flush()
