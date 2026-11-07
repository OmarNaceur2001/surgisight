"""Tool usage analytics and temporal hysteresis filtering."""

from __future__ import annotations

from surgisight.contract.models import ToolPresencePrediction, ToolUsage
from surgisight.contract.types import TOOL_ORDER


def filter_presence_hysteresis(
    probabilities: list[float],
    high_threshold: float = 0.60,
    low_threshold: float = 0.35,
    min_run_length: int = 2,
) -> list[bool]:
    """Apply two-threshold Schmitt trigger / hysteresis with minimum run length to reduce flicker.

    State transitions:
    - Inactive -> Active: when probability >= high_threshold for min_run_length consecutive steps.
    - Active -> Inactive: when probability < low_threshold for min_run_length consecutive steps.
    """
    n = len(probabilities)
    if n == 0:
        return []

    active_state = False
    result = [False] * n

    i = 0
    while i < n:
        if not active_state:
            # Check for activation burst
            if probabilities[i] >= high_threshold:
                # Check run length
                burst_len = 0
                while i + burst_len < n and probabilities[i + burst_len] >= high_threshold:
                    burst_len += 1
                if burst_len >= min_run_length:
                    active_state = True
                    for j in range(i, i + burst_len):
                        result[j] = True
                    i += burst_len
                    continue
            result[i] = False
            i += 1
        else:
            # Check for deactivation burst
            if probabilities[i] < low_threshold:
                drop_len = 0
                while i + drop_len < n and probabilities[i + drop_len] < low_threshold:
                    drop_len += 1
                if drop_len >= min_run_length:
                    active_state = False
                    for j in range(i, i + drop_len):
                        result[j] = False
                    i += drop_len
                    continue
            result[i] = True
            i += 1

    return result


def compute_tool_usage_summaries(
    tool_predictions: list[ToolPresencePrediction],
    duration_s: float,
    apply_hysteresis: bool = True,
) -> list[ToolUsage]:
    """Calculate aggregated usage duration and percentage for each of the 7 tools.

    Percentages reflect presence fraction over surgery duration; because instruments
    are routinely used concurrently (e.g. Grasper + Hook), percentages do not sum to 100%.
    """
    total_duration = max(1.0, float(duration_s))
    summaries: list[ToolUsage] = []

    for tool in TOOL_ORDER:
        probs = [p.probs.get(tool, 0.0) for p in tool_predictions]
        if apply_hysteresis:
            active_mask = filter_presence_hysteresis(probs)
        else:
            active_mask = [p >= 0.50 for p in probs]

        usage_seconds = float(sum(active_mask))
        percentage = round((usage_seconds / total_duration) * 100.0, 2)

        summaries.append(
            ToolUsage(
                tool=tool,
                usage_s=round(usage_seconds, 2),
                pct=percentage,
            )
        )

    return summaries
