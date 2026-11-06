"""Tests for SurgiSight Data Contract v1.0.

Covers:
- Valid and invalid schema cases
- Interval tiling validation (gaps, overlaps, duration mismatch)
- Property-based testing with Hypothesis (half-open intervals, tiling, frame conversions)
- Deterministic mock generator (20-90 min videos, phase order, tiling, seed reproducibility)
- Schema compatibility check against committed JSON Schema files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from surgisight.contract import (
    PHASE_NAMES,
    PHASE_ORDER,
    PHASE_PALETTE,
    TOOL_ORDER,
    TOOL_PALETTE,
    AnalysisRun,
    Correction,
    DetectionRecord,
    MockAnalysisResult,
    PerSecondRecord,
    PhaseId,
    PhasePrediction,
    PhaseSegment,
    ProducerInfo,
    Report,
    ReportStatus,
    StreamMessage,
    TimeInterval,
    ToolId,
    ToolPresencePrediction,
    Track,
    VideoMeta,
    frame_idx_to_seconds,
    generate_mock_analysis,
    seconds_to_frame_idx,
    validate_interval_tiling,
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def producer() -> ProducerInfo:
    return ProducerInfo(name="test_runner", version="1.0.0")


# ==============================================================================
# 1. Basic Models & Validation
# ==============================================================================


def test_time_interval_valid() -> None:
    interval = TimeInterval(start=10.0, end=20.5)
    assert interval.start == 10.0
    assert interval.end == 20.5
    assert interval.duration == 10.5
    assert interval.contains(10.0) is True
    assert interval.contains(15.2) is True
    assert interval.contains(20.5) is False  # Half-open: end is exclusive
    assert interval.contains(9.99) is False


def test_time_interval_invalid() -> None:
    with pytest.raises(ValidationError):
        TimeInterval(start=20.0, end=10.0)

    with pytest.raises(ValidationError):
        TimeInterval(start=10.0, end=10.0)

    with pytest.raises(ValidationError):
        TimeInterval(start=-1.0, end=5.0)


def test_phase_prediction_valid() -> None:
    probs = dict.fromkeys(PHASE_ORDER, 0.05)
    probs[PhaseId.P1] = 0.70
    pred = PhasePrediction(label=PhaseId.P1, probs=probs)
    assert pred.label == PhaseId.P1
    assert pred.name == "Preparation"
    assert pred.confidence == 0.70


def test_phase_prediction_missing_phase() -> None:
    probs = {PhaseId.P1: 0.90, PhaseId.P2: 0.10}
    with pytest.raises(ValidationError, match="must contain all 7 phases"):
        PhasePrediction(label=PhaseId.P1, probs=probs)  # type: ignore[arg-type]


def test_phase_prediction_probs_not_sum_to_one() -> None:
    probs = dict.fromkeys(PHASE_ORDER, 0.5)  # sum = 3.5
    with pytest.raises(ValidationError, match="must sum to approximately 1.0"):
        PhasePrediction(label=PhaseId.P1, probs=probs)


def test_tool_presence_valid() -> None:
    probs = dict.fromkeys(TOOL_ORDER, 0.1)
    probs[ToolId.GRASPER] = 0.95
    tp = ToolPresencePrediction(probs=probs)
    assert tp.is_present(ToolId.GRASPER) is True
    assert tp.is_present(ToolId.HOOK) is False


def test_detection_record_bbox_validation(producer: ProducerInfo) -> None:
    # Valid
    det = DetectionRecord(
        producer=producer,
        t=12.4,
        tool=ToolId.HOOK,
        bbox=[100.0, 50.0, 200.0, 150.0],
        score=0.92,
    )
    assert det.bbox == [100.0, 50.0, 200.0, 150.0]

    # Invalid: x2 <= x1
    with pytest.raises(ValidationError, match="x2 > x1"):
        DetectionRecord(
            producer=producer,
            t=12.4,
            tool=ToolId.HOOK,
            bbox=[200.0, 50.0, 100.0, 150.0],
            score=0.92,
        )

    # Invalid: wrong number of coordinates
    with pytest.raises(ValidationError, match="must have 4 coordinates"):
        DetectionRecord(
            producer=producer,
            t=12.4,
            tool=ToolId.HOOK,
            bbox=[100.0, 50.0, 200.0],
            score=0.92,
        )


# ==============================================================================
# 2. Interval Tiling Tests (No Gap, No Overlap)
# ==============================================================================


def test_validate_interval_tiling_perfect() -> None:
    segs = [
        PhaseSegment(label=PhaseId.P1, name="Preparation", start=0.0, end=100.0, conf=0.9),
        PhaseSegment(
            label=PhaseId.P2, name=PHASE_NAMES[PhaseId.P2], start=100.0, end=250.0, conf=0.85
        ),
        PhaseSegment(
            label=PhaseId.P3, name=PHASE_NAMES[PhaseId.P3], start=250.0, end=400.0, conf=0.88
        ),
    ]
    validate_interval_tiling(segs, duration_s=400.0)


def test_validate_interval_tiling_gap_detected() -> None:
    segs = [
        PhaseSegment(label=PhaseId.P1, name="Preparation", start=0.0, end=100.0, conf=0.9),
        # Gap of 10s: 100.0 to 110.0
        PhaseSegment(
            label=PhaseId.P2, name=PHASE_NAMES[PhaseId.P2], start=110.0, end=250.0, conf=0.85
        ),
    ]
    with pytest.raises(ValueError, match="Tiling gap"):
        validate_interval_tiling(segs, duration_s=250.0)


def test_validate_interval_tiling_overlap_detected() -> None:
    segs = [
        PhaseSegment(label=PhaseId.P1, name="Preparation", start=0.0, end=120.0, conf=0.9),
        # Overlap of 20s: starts at 100.0 while previous ends at 120.0
        PhaseSegment(
            label=PhaseId.P2, name=PHASE_NAMES[PhaseId.P2], start=100.0, end=250.0, conf=0.85
        ),
    ]
    with pytest.raises(ValueError, match="Tiling overlap"):
        validate_interval_tiling(segs, duration_s=250.0)


def test_validate_interval_tiling_wrong_start() -> None:
    segs = [
        PhaseSegment(label=PhaseId.P1, name="Preparation", start=5.0, end=100.0, conf=0.9),
    ]
    with pytest.raises(ValueError, match="first segment starts at"):
        validate_interval_tiling(segs, duration_s=100.0)


def test_validate_interval_tiling_wrong_end() -> None:
    segs = [
        PhaseSegment(label=PhaseId.P1, name="Preparation", start=0.0, end=90.0, conf=0.9),
    ]
    with pytest.raises(ValueError, match="last segment ends at 90.0s, video duration is 100.0s"):
        validate_interval_tiling(segs, duration_s=100.0)


# ==============================================================================
# 3. Property-Based Testing with Hypothesis
# ==============================================================================


@given(
    durs=st.lists(
        st.floats(min_value=1.0, max_value=300.0, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=7,
    )
)
def test_hypothesis_generated_tiling(durs: list[float]) -> None:
    """Any sequence of consecutive positive durations perfectly tiles its total span."""
    segments: list[PhaseSegment] = []
    t = 0.0
    phases = list(PhaseId)
    for i, dur in enumerate(durs):
        start = round(t, 2)
        end = round(t + dur, 2)
        phase_label = phases[i % len(phases)]
        segments.append(
            PhaseSegment(
                label=phase_label,
                name=PHASE_NAMES[phase_label],
                start=start,
                end=end,
                conf=0.9,
            )
        )
        t = end

    total_duration = round(t, 2)
    validate_interval_tiling(segments, total_duration)


@given(
    start=st.floats(min_value=0.0, max_value=1000.0),
    length=st.floats(min_value=0.05, max_value=500.0),
)
def test_hypothesis_half_open_boundaries(start: float, length: float) -> None:
    """Verify half-open interval property: start is included, end is excluded."""
    start_r = round(start, 2)
    end_r = round(start + length, 2)
    if end_r <= start_r:
        end_r = start_r + 0.01

    interval = TimeInterval(start=start_r, end=end_r)
    assert interval.contains(start_r) is True
    assert interval.contains(end_r) is False
    assert interval.contains(start_r + (end_r - start_r) / 2) is True


@given(t=st.floats(min_value=0.0, max_value=7200.0))
def test_hypothesis_time_frame_conversion(t: float) -> None:
    """Conversion from seconds -> frame_idx -> seconds is within 1/fps precision."""
    fps = 25.0
    t_round = round(t, 2)
    frame_idx = seconds_to_frame_idx(t_round, fps=fps)
    t_recovered = frame_idx_to_seconds(frame_idx, fps=fps)

    # Must be within one frame duration (1/25 = 0.04s)
    assert abs(t_recovered - t_round) <= 0.04


# ==============================================================================
# 4. Mock Generator Tests
# ==============================================================================


@pytest.mark.parametrize("duration_min", [20.0, 35.0, 60.0, 90.0])
def test_mock_generator_validates(duration_min: float) -> None:
    """Mock analysis output must pass all Pydantic validators and tiling checks."""
    result: MockAnalysisResult = generate_mock_analysis(
        duration_minutes=duration_min, seed=42, video_id=f"test_{int(duration_min)}"
    )

    expected_duration_s = round(duration_min * 60.0, 2)
    assert result.report.duration_s == expected_duration_s
    assert result.report.status == ReportStatus.DRAFT_PENDING_REVIEW
    assert "not for clinical use" in result.report.disclaimer.lower()

    # Tiling check on the generated report
    validate_interval_tiling(result.report.phases, expected_duration_s)

    # 7 phases present in expected order
    labels = [s.label for s in result.report.phases]
    assert labels == PHASE_ORDER

    # Tool usages
    assert len(result.report.tools) == 7

    # Check 1 Hz records
    assert len(result.per_second_records) == int(expected_duration_s)
    assert result.per_second_records[0].t == 0.0
    assert result.per_second_records[-1].t == float(int(expected_duration_s) - 1)

    # Check 5 Hz detections
    assert len(result.detection_records) > 0
    for det in result.detection_records[:50]:
        assert det.tool in TOOL_ORDER
        assert det.bbox[2] > det.bbox[0]
        assert det.bbox[3] > det.bbox[1]


def test_mock_generator_deterministic() -> None:
    """Same seed must produce bit-for-bit identical results."""
    run1 = generate_mock_analysis(duration_minutes=25.0, seed=123)
    run2 = generate_mock_analysis(duration_minutes=25.0, seed=123)

    assert run1.report.model_dump() == run2.report.model_dump()
    assert [r.model_dump() for r in run1.per_second_records[:100]] == [
        r.model_dump() for r in run2.per_second_records[:100]
    ]


def test_mock_generator_different_seeds() -> None:
    """Different seeds must produce different phase boundary distributions."""
    run1 = generate_mock_analysis(duration_minutes=30.0, seed=1)
    run2 = generate_mock_analysis(duration_minutes=30.0, seed=2)

    durations1 = [s.duration_s for s in run1.report.phases]
    durations2 = [s.duration_s for s in run2.report.phases]
    assert durations1 != durations2


# ==============================================================================
# 5. Schema Compatibility Test (Freezing Contract v1.0)
# ==============================================================================


@pytest.mark.parametrize(
    ("schema_filename", "model_cls"),
    [
        ("PerSecondRecord.schema.json", PerSecondRecord),
        ("DetectionRecord.schema.json", DetectionRecord),
        ("Track.schema.json", Track),
        ("Report.schema.json", Report),
        ("Correction.schema.json", Correction),
        ("StreamMessage.schema.json", StreamMessage),
        ("VideoMeta.schema.json", VideoMeta),
        ("AnalysisRun.schema.json", AnalysisRun),
    ],
)
def test_schema_compatibility_with_frozen_files(
    schema_filename: str, model_cls: type[Report]
) -> None:
    """Ensure active Pydantic models match the committed JSON Schema files.

    Any intentional schema change must bump the contract version and update CHANGELOG.md.
    """
    schema_file = ROOT / "contract" / "schemas" / schema_filename
    assert schema_file.exists(), f"Committed schema file missing: {schema_file}"

    committed_schema = json.loads(schema_file.read_text(encoding="utf-8"))
    active_schema = model_cls.model_json_schema()

    # Compare title, properties, and required fields
    assert active_schema.get("title") == committed_schema.get("title")
    assert active_schema.get("required") == committed_schema.get("required")
    assert set(active_schema.get("properties", {}).keys()) == set(
        committed_schema.get("properties", {}).keys()
    )


def test_palette_consistency() -> None:
    """Verify phase and tool palettes define all expected entities with valid color formats."""
    assert len(PHASE_PALETTE) == 7
    for phase_id in PHASE_ORDER:
        assert phase_id.value in PHASE_PALETTE
        item = PHASE_PALETTE[phase_id.value]
        assert item["hex"].startswith("#")
        assert len(item["hex"]) == 7
        assert item["name"] == PHASE_NAMES[phase_id]

    assert len(TOOL_PALETTE) == 7
    for tool_id in TOOL_ORDER:
        assert tool_id.value in TOOL_PALETTE
        item = TOOL_PALETTE[tool_id.value]
        assert item["hex"].startswith("#")
        assert len(item["hex"]) == 7
