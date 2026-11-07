"""SurgiSight Analytics Module (M5).

Provides:
- Surgical milestone event detection with conflict precedence resolution
- Tool presence hysteresis and multi-tool concurrency metrics
- Reference cohort duration comparison and neutral deviation detection
- Confidence calibration and uncertainty evaluation
- Principle P3 lexicon validation
"""

from surgisight.analytics.calibration import (
    apply_temperature_scaling,
    compute_expected_calibration_error,
    is_uncertain,
)
from surgisight.analytics.deviations import detect_cohort_deviations
from surgisight.analytics.events import detect_surgical_events
from surgisight.analytics.lexicon import (
    find_forbidden_words,
    load_forbidden_words,
    validate_object_lexicon,
    validate_text_lexicon,
)
from surgisight.analytics.tool_usage import (
    compute_tool_usage_summaries,
    filter_presence_hysteresis,
)

__all__ = [
    "apply_temperature_scaling",
    "compute_expected_calibration_error",
    "compute_tool_usage_summaries",
    "detect_cohort_deviations",
    "detect_surgical_events",
    "filter_presence_hysteresis",
    "find_forbidden_words",
    "is_uncertain",
    "load_forbidden_words",
    "validate_object_lexicon",
    "validate_text_lexicon",
]
