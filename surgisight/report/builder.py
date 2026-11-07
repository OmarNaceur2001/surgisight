"""Report builder conforming to Data Contract v1.0 and Principle P3."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from surgisight.analytics.lexicon import validate_object_lexicon
from surgisight.contract.models import (
    Deviation,
    KeyEvent,
    PhaseSegment,
    ProducerInfo,
    Report,
    ToolUsage,
    TripletHighlight,
    validate_interval_tiling,
)
from surgisight.contract.types import (
    CONTRACT_VERSION,
    RESEARCH_DISCLAIMER,
    ReportStatus,
)


def build_report(
    video_id: UUID,
    dataset: str,
    duration_s: float,
    phases: list[PhaseSegment],
    tools: list[ToolUsage],
    events: list[KeyEvent],
    deviations: list[Deviation],
    triplet_highlights: list[TripletHighlight],
    models: dict[str, str],
    confidence_notes: list[str] | None = None,
    status: ReportStatus = ReportStatus.DRAFT_PENDING_REVIEW,
    cvs: dict[str, Any] | None = None,
    summary: str | None = None,
) -> Report:
    """Build and validate an operative report conforming to Data Contract v1.0.

    Guarantees:
    - Phase segments tile [0.0, duration_s) with no gap and no overlap.
    - Research disclaimer is included.
    - All text strictly complies with Principle P3 wording lexicon.
    """
    total_dur = round(float(duration_s), 2)
    validate_interval_tiling(phases, total_dur)

    notes = confidence_notes or []
    # If any phase or event is uncertain, document it in confidence notes
    uncertain_phases = [p.name for p in phases if p.uncertain]
    if uncertain_phases and not any("phase classification" in n for n in notes):
        notes.append(
            f"Phase classification confidence below threshold for {len(uncertain_phases)} segment(s); flagged for human review."
        )

    uncertain_events = [e.type for e in events if e.uncertain]
    if uncertain_events and not any("event detection" in n for n in notes):
        notes.append(
            f"Event detection confidence below threshold or signal discrepancy noted for {len(uncertain_events)} milestone(s)."
        )

    report = Report(
        schema_version=CONTRACT_VERSION,
        producer=ProducerInfo(name="surgisight.report.builder", version=CONTRACT_VERSION),
        video_id=video_id,
        dataset=dataset,
        duration_s=total_dur,
        status=status,
        disclaimer=RESEARCH_DISCLAIMER,
        phases=phases,
        tools=tools,
        events=events,
        deviations=deviations,
        triplet_highlights=triplet_highlights,
        cvs=cvs,
        confidence_notes=notes,
        models=models,
        summary=summary,
    )

    # Principle P3: Enforce wording lexicon recursively across entire report object
    validate_object_lexicon(report.model_dump(), path="report")

    return report
