"""Deterministic, report-grounded summary generation and fact checking (WP11)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from surgisight.analytics.lexicon import validate_text_lexicon
from surgisight.contract.models import Report

_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?(?![A-Za-z])")
_PHASE_PATTERN = re.compile(r"\bP[1-7]\b")


@dataclass(frozen=True)
class SummaryCheck:
    """Result of deterministic checks against the source report JSON."""

    valid: bool
    reasons: tuple[str, ...]
    numeric_tokens_checked: int


def _decimal_token(value: str | int | float) -> Decimal:
    """Normalize a number for exact comparison without formatting assumptions."""
    try:
        return Decimal(str(value)).normalize()
    except InvalidOperation:
        return Decimal("NaN")


def _allowed_numbers(report: Report) -> set[Decimal]:
    """Extract every numeric value that a report-grounded summary may state."""
    values: list[float | int] = [report.duration_s]
    for phase in report.phases:
        values.extend((phase.start, phase.end, phase.conf))
    for tool in report.tools:
        values.extend((tool.usage_s, tool.pct))
    for event in report.events:
        values.extend((event.t, event.conf))
    for triplet in report.triplet_highlights:
        values.extend((triplet.ivt_id, triplet.t, triplet.score))
    normalized: set[Decimal] = set()
    for value in values:
        normalized.add(_decimal_token(value))
        normalized.add(_decimal_token(round(float(value), 2)))
    return normalized


def fact_check_summary(summary: str, report: Report) -> SummaryCheck:
    """Reject lexical violations, unsupported numbers, phases, or tool names."""
    reasons: list[str] = []
    try:
        validate_text_lexicon(summary, context="generated summary")
    except ValueError as exc:
        reasons.append(str(exc))

    allowed_numbers = _allowed_numbers(report)
    numeric_tokens = _NUMBER_PATTERN.findall(summary)
    for token in numeric_tokens:
        if _decimal_token(token) not in allowed_numbers:
            reasons.append(f"Unsupported numeric value: {token}")

    allowed_phases = {phase.label.value for phase in report.phases}
    for phase in _PHASE_PATTERN.findall(summary):
        if phase not in allowed_phases:
            reasons.append(f"Phase {phase} is absent from the source report")

    source_events = {event.type for event in report.events}
    event_start = summary.find("Recorded event markers:")
    triplet_start = summary.find("Triplet highlights:", event_start)
    if event_start >= 0 and triplet_start > event_start:
        event_section = summary[event_start + len("Recorded event markers:"):triplet_start]
        if "No event markers are listed" not in event_section:
            for entry in event_section.split(";"):
                event_name = entry.strip().split(" at ", maxsplit=1)[0]
                if event_name and event_name not in source_events:
                    reasons.append(f"Event {event_name} is absent from the source report")

    source_triplets = {item.ivt_name for item in report.triplet_highlights}
    if triplet_start >= 0:
        triplet_section = summary[triplet_start + len("Triplet highlights:"):]
        if "No triplet highlights are listed" not in triplet_section:
            for entry in triplet_section.split(";"):
                triplet_name = entry.strip().split(" at ", maxsplit=1)[0]
                if triplet_name and triplet_name not in source_triplets:
                    reasons.append(f"Triplet {triplet_name} is absent from the source report")

    allowed_tools = {tool.tool.value for tool in report.tools}
    for candidate in (
        "Grasper", "Bipolar", "Hook", "Scissors", "Clipper", "Irrigator", "SpecimenBag"
    ):
        if re.search(rf"\b{re.escape(candidate)}\b", summary) and candidate not in allowed_tools:
            reasons.append(f"Tool {candidate} is absent from the source report")

    return SummaryCheck(
        valid=not reasons,
        reasons=tuple(reasons),
        numeric_tokens_checked=len(numeric_tokens),
    )


def generate_grounded_summary(report: Report) -> tuple[str, SummaryCheck]:
    """Generate a short deterministic summary exclusively from validated report fields."""
    phase_text = "; ".join(
        f"{phase.label.value} ({phase.name}) from {phase.start:.2f} to {phase.end:.2f} seconds"
        for phase in report.phases
    )
    tool_text = "; ".join(
        f"{tool.tool.value}: {tool.usage_s:.2f} seconds ({tool.pct:.2f} percent)"
        for tool in report.tools
    )
    event_text = (
        "; ".join(
            f"{event.type} at {event.t:.2f} seconds, confidence {event.conf:.2f}"
            for event in report.events
        )
        if report.events
        else "No event markers are listed in the report."
    )
    triplet_text = (
        "; ".join(
            f"{item.ivt_name} at {item.t:.2f} seconds (score {item.score:.2f})"
            for item in report.triplet_highlights
        )
        if report.triplet_highlights
        else "No triplet highlights are listed in the report."
    )
    summary = (
        f"AI-generated, report-grounded summary: This research record covers "
        f"{report.duration_s:.2f} seconds of video. "
        f"Phase intervals: {phase_text or 'none listed'}. "
        f"Instrument presence summaries: {tool_text or 'none listed'}. "
        f"Recorded event markers: {event_text} "
        f"Triplet highlights: {triplet_text} "
        f"Review state: {report.status.value}."
    )
    check = fact_check_summary(summary, report)
    if not check.valid:
        raise ValueError(f"Generated summary did not pass its report checks: {check.reasons}")
    return summary, check
