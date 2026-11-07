"""Cohort statistics comparison and neutral deviation detection."""

from __future__ import annotations

from typing import Any

from surgisight.analytics.lexicon import validate_text_lexicon
from surgisight.contract.models import Deviation, PhaseSegment
from surgisight.contract.types import PHASE_NAMES, PhaseId

# Default reference cohort duration statistics (laparoscopic cholecystectomy cohort baseline)
# 95th percentile duration in seconds derived from reference public datasets (e.g. Cholec80 reference)
DEFAULT_COHORT_P95_SECONDS: dict[PhaseId, float] = {
    PhaseId.P1: 420.0,  # 7.0 min
    PhaseId.P2: 1800.0,  # 30.0 min
    PhaseId.P3: 600.0,  # 10.0 min
    PhaseId.P4: 1500.0,  # 25.0 min
    PhaseId.P5: 480.0,  # 8.0 min
    PhaseId.P6: 720.0,  # 12.0 min
    PhaseId.P7: 300.0,  # 5.0 min
}

DEFAULT_COHORT_N = 80


def detect_cohort_deviations(
    phase_segments: list[PhaseSegment],
    cohort_stats: dict[PhaseId, dict[str, Any]] | None = None,
) -> list[Deviation]:
    """Detect phase duration outliers against the reference cohort.

    Adheres strictly to Principle P3: 'Describe, never judge'. Wording always states
    that the duration is 'outside the observed range of the reference cohort' without
    pejorative, judgmental, or clinical performance language.
    """
    # Aggregate total duration per phase (in case of non-consecutive segments)
    durations: dict[PhaseId, float] = {}
    for seg in phase_segments:
        durations[seg.label] = durations.get(seg.label, 0.0) + seg.duration_s

    deviations: list[Deviation] = []

    for phase_id, total_dur in durations.items():
        phase_name = PHASE_NAMES[phase_id]

        if cohort_stats and phase_id in cohort_stats:
            p95 = float(cohort_stats[phase_id].get("p95", DEFAULT_COHORT_P95_SECONDS[phase_id]))
            n = int(cohort_stats[phase_id].get("n", DEFAULT_COHORT_N))
        else:
            p95 = DEFAULT_COHORT_P95_SECONDS.get(phase_id, 1200.0)
            n = DEFAULT_COHORT_N

        if total_dur > p95:
            wording = (
                f"Phase {phase_id.value} ({phase_name}) duration ({total_dur:.1f}s) is outside the "
                f"observed range of the reference cohort (p95: {p95:.1f}s, n={n})."
            )
            # Ensure text complies with P3 lexicon
            validate_text_lexicon(wording, context=f"Deviation {phase_id.value}")

            deviations.append(
                Deviation(
                    type="phase_duration_exceeded",
                    phase=phase_id,
                    value_s=round(total_dur, 2),
                    cohort_p95_s=round(p95, 2),
                    cohort_n=n,
                    wording=wording,
                )
            )

    return deviations
