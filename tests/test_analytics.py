"""Unit tests for SurgiSight Analytics Engine (M5) and Wording Lexicon (P3)."""

from __future__ import annotations

import numpy as np
import pytest

from surgisight.analytics.calibration import (
    apply_temperature_scaling,
    compute_expected_calibration_error,
    is_uncertain,
)
from surgisight.analytics.deviations import detect_cohort_deviations
from surgisight.analytics.events import detect_surgical_events
from surgisight.analytics.lexicon import (
    find_forbidden_words,
    validate_object_lexicon,
    validate_text_lexicon,
)
from surgisight.analytics.tool_usage import (
    compute_tool_usage_summaries,
    filter_presence_hysteresis,
)
from surgisight.contract.models import (
    PhasePrediction,
    PhaseSegment,
    ToolPresencePrediction,
)
from surgisight.contract.types import PHASE_ORDER, TOOL_ORDER, PhaseId, ToolId


def _make_phase_pred(label: PhaseId, conf: float = 0.90) -> PhasePrediction:
    rem = (1.0 - conf) / 6.0
    probs = {p: (conf if p == label else rem) for p in PHASE_ORDER}
    return PhasePrediction(label=label, probs=probs)


def _make_tool_pred(active_tools: dict[ToolId, float]) -> ToolPresencePrediction:
    probs = {t: active_tools.get(t, 0.05) for t in TOOL_ORDER}
    return ToolPresencePrediction(probs=probs)


class TestAnalyticsEvents:
    def test_conflict_first_clip_during_p2(self):
        """Prompt requirement: clip at 501s while P2 runs to 520s MUST be flagged uncertain."""
        # Construct 600-second timeline:
        # 0..520s is P2 (Calot dissection)
        # 521..600s is P3 (Clipping and cutting)
        phases = [
            _make_phase_pred(PhaseId.P2) if t <= 520 else _make_phase_pred(PhaseId.P3)
            for t in range(600)
        ]

        # Clipper activates at 501s with p=0.85 (conflict!)
        tools = []
        for t in range(600):
            if t == 501:
                tools.append(_make_tool_pred({ToolId.CLIPPER: 0.85}))
            else:
                tools.append(_make_tool_pred({}))

        events = detect_surgical_events(phase_predictions=phases, tool_predictions=tools)

        first_clip_events = [e for e in events if e.type == "first_clip"]
        assert len(first_clip_events) == 1
        clip_ev = first_clip_events[0]

        # Milestone detected at 501s
        assert clip_ev.t == 501.0
        # MUST be flagged uncertain due to conflict with Phase P2
        assert clip_ev.uncertain is True
        # Evidence must document the discrepancy
        assert any("P2" in ev for ev in clip_ev.evidence)
        assert any("Discrepancy flagged" in ev for ev in clip_ev.evidence)

    def test_canonical_event_sequence(self):
        """Standard sequence of milestones without conflicts."""
        # 100s P2, then 100s P3, then 100s P4
        phases = (
            [_make_phase_pred(PhaseId.P2)] * 100
            + [_make_phase_pred(PhaseId.P3)] * 100
            + [_make_phase_pred(PhaseId.P4)] * 100
        )
        tools = [_make_tool_pred({})] * 300
        # Clipper at 120s (inside P3)
        tools[120] = _make_tool_pred({ToolId.CLIPPER: 0.90})
        # Scissors at 150s (inside P3)
        tools[150] = _make_tool_pred({ToolId.SCISSORS: 0.85})

        events = detect_surgical_events(phase_predictions=phases, tool_predictions=tools)
        event_types = [e.type for e in events]

        assert "calot_dissection_start" in event_types
        assert "first_clip" in event_types
        assert "cystic_duct_cut" in event_types
        assert "gallbladder_dissection_start" in event_types

        clip_ev = next(e for e in events if e.type == "first_clip")
        assert clip_ev.uncertain is False
        assert clip_ev.t == 120.0


class TestToolUsageHysteresis:
    def test_hysteresis_flicker_reduction(self):
        """Single-frame drops do not terminate active tool usage."""
        # Probabilities: 2 frames high, 1 frame drop, 2 frames high
        probs = [0.8, 0.85, 0.1, 0.9, 0.85]
        active = filter_presence_hysteresis(
            probs, high_threshold=0.60, low_threshold=0.35, min_run_length=2
        )

        # Single drop at index 2 is filtered out (remains active)
        assert active == [True, True, True, True, True]

    def test_tool_usage_summary_calculation(self):
        """Usage summaries calculate usage_s and pct correctly without requiring 100% sum."""
        preds = [_make_tool_pred({ToolId.GRASPER: 0.80, ToolId.HOOK: 0.75}) for _ in range(60)] + [
            _make_tool_pred({ToolId.GRASPER: 0.80}) for _ in range(40)
        ]

        summaries = compute_tool_usage_summaries(preds, duration_s=100.0)
        grasper_summary = next(s for s in summaries if s.tool == ToolId.GRASPER)
        hook_summary = next(s for s in summaries if s.tool == ToolId.HOOK)

        assert grasper_summary.usage_s == 100.0
        assert grasper_summary.pct == 100.0
        assert hook_summary.usage_s == 60.0
        assert hook_summary.pct == 60.0

        # Percentages sum to > 100% due to concurrent multi-tool usage
        total_pct = sum(s.pct for s in summaries)
        assert total_pct > 100.0


class TestDeviationsAndLexicon:
    def test_cohort_deviation_neutral_wording(self):
        """Deviations strictly follow P3 neutral phrasing: outside observed range of reference cohort."""
        segments = [
            PhaseSegment(
                label=PhaseId.P2,
                name="Calot triangle dissection",
                start=0.0,
                end=2000.0,  # exceeds default P2 p95 of 1800s
                conf=0.85,
                uncertain=False,
            )
        ]
        deviations = detect_cohort_deviations(segments)
        assert len(deviations) == 1
        dev = deviations[0]

        assert dev.phase == PhaseId.P2
        assert "outside the observed range of the reference cohort" in dev.wording
        # Ensure no forbidden words
        assert not find_forbidden_words(dev.wording)

    def test_forbidden_words_detection(self):
        """Principle P3 forbids evaluative terms."""
        assert "error" in find_forbidden_words("Surgical error during dissection")
        assert "mistake" in find_forbidden_words("Technical mistake identified")
        assert "complication" in find_forbidden_words("Postoperative complication noted")
        assert "incompetent" in find_forbidden_words("Operator deemed incompetent")

        with pytest.raises(ValueError, match="Principle P3 violation"):
            validate_text_lexicon("A critical mistake was detected.")

        with pytest.raises(ValueError, match="Principle P3 violation"):
            validate_object_lexicon({"notes": ["Procedure had minor errors"]})

    def test_clean_text_passes_lexicon(self):
        """Neutral technical descriptions pass validation."""
        clean_text = (
            "Phase P2 (Calot triangle dissection) duration is outside the observed range of the "
            "reference cohort (p95: 1800.0s, n=80). Review requested for signal discrepancy."
        )
        validate_text_lexicon(clean_text)
        assert find_forbidden_words(clean_text) == []


class TestCalibration:
    def test_ece_computation(self):
        """Perfect calibration yields ECE near 0.0."""
        confidences = np.array([0.9, 0.9, 0.9, 0.9, 0.9])
        accuracies = np.array([1, 1, 1, 1, 1])  # 100% accuracy vs 90% confidence
        ece = compute_expected_calibration_error(confidences, accuracies)
        assert ece == pytest.approx(0.1, abs=0.02)

    def test_temperature_scaling(self):
        """Temperature scaling softens probabilities as T increases."""
        logits = np.array([[2.0, 1.0, 0.0]])
        probs_t1 = apply_temperature_scaling(logits, temperature=1.0)
        probs_t2 = apply_temperature_scaling(logits, temperature=2.0)

        # Higher T leads to higher entropy (lower max probability)
        assert np.max(probs_t2) < np.max(probs_t1)
        assert np.isclose(np.sum(probs_t2), 1.0)

    def test_is_uncertain(self):
        assert is_uncertain(0.49, threshold=0.50) is True
        assert is_uncertain(0.50, threshold=0.50) is False
        assert is_uncertain(0.75, threshold=0.50) is False
