"""Deterministic, report-grounded summary generation and fact checking (WP11)."""

from __future__ import annotations

from dataclasses import dataclass

from surgisight.analytics.lexicon import validate_text_lexicon
from surgisight.contract.models import Report


@dataclass(frozen=True)
class SummaryCheck:
    """Result of validating a generated summary against canonical report data."""

    accepted: bool
    reason: str


def generate_grounded_summary(report: Report) -> str:
    """Create a deterministic summary using only values in the report JSON.

    This is a template implementation, not an external language-model call.
    """
    phase_sequence = ", ".join(dict.fromkeys(phase.label.value for phase in report.phases))
    tool_names = ", ".join(tool.tool.value for tool in report.tools)
    event_names = ", ".join(event.type.replace("_", " ") for event in report.events)
    return (
        f"The analysis record spans {report.duration_s:.2f} seconds and contains "
        f"{len(report.phases)} phase segments. Recorded phase sequence: {phase_sequence}. "
        f"Instrument entries: {tool_names or 'none recorded'}. "
        f"Key events recorded: {len(report.events)}"
        f"{f' ({event_names})' if event_names else ''}."
    )


def check_grounded_summary(summary: str, report: Report) -> SummaryCheck:
    """Accept only the deterministic summary regenerated from the validated report.

    Exact-template checking ensures every number, phase, instrument and event in
    this initial implementation is sourced from the canonical report JSON.
    """
    try:
        validate_text_lexicon(summary, context="generated summary")
    except ValueError:
        return SummaryCheck(accepted=False, reason="Blocked by the neutral wording lexicon.")

    expected = generate_grounded_summary(report)
    if summary.strip() != expected:
        return SummaryCheck(
            accepted=False,
            reason="Summary contains content that is not present in the canonical report-derived template.",
        )
    return SummaryCheck(accepted=True, reason="All summary content matches the canonical report-derived template.")


def generate_checked_summary(report: Report) -> str | None:
    """Return a checked summary, or omit it when validation does not accept it."""
    summary = generate_grounded_summary(report)
    check = check_grounded_summary(summary, report)
    return summary if check.accepted else None
