"""Stage 2 replay conversion and grounded-summary checks (synthetic only)."""

from __future__ import annotations

from surgisight.contract import generate_mock_analysis
from surgisight.contract.models import PhaseId, ToolId
from surgisight.report.summary import check_grounded_summary, generate_grounded_summary
from surgisight.api.routers.stage2 import prediction_to_record


def test_online_prediction_converts_to_contract_record() -> None:
    raw = {
        "t": 12.0,
        "frame_idx": 300,
        "phase": {
            "label": "P2",
            "probs": [0.01, 0.90, 0.02, 0.02, 0.02, 0.02, 0.01],
        },
        "tools": [0.9, 0.2, 0.7, 0.1, 0.1, 0.1, 0.0],
        "triplets": [],
        "quality_flags": [],
    }
    record = prediction_to_record(raw, producer_version="fixture")
    assert record.t == 12.0
    assert record.frame_idx == 300
    assert record.phase.label == PhaseId.P2
    assert record.tools.probs[ToolId.GRASPER] == 0.9
    assert record.producer.version == "fixture"


def test_grounded_summary_matches_only_canonical_report_values() -> None:
    report = generate_mock_analysis(duration_minutes=20.0, seed=37).report
    summary = generate_grounded_summary(report)
    assert check_grounded_summary(summary, report).accepted is True


def test_grounded_summary_rejects_injected_number() -> None:
    report = generate_mock_analysis(duration_minutes=20.0, seed=37).report
    summary = generate_grounded_summary(report) + " The duration is 123456 seconds."
    check = check_grounded_summary(summary, report)
    assert check.accepted is False


def test_grounded_summary_rejects_evaluative_wording() -> None:
    report = generate_mock_analysis(duration_minutes=20.0, seed=37).report
    summary = generate_grounded_summary(report) + " The surgeon was poor."
    check = check_grounded_summary(summary, report)
    assert check.accepted is False


def test_grounded_summary_rejects_changed_phase_label() -> None:
    report = generate_mock_analysis(duration_minutes=20.0, seed=37).report
    summary = generate_grounded_summary(report).replace("P1", "P9")
    check = check_grounded_summary(summary, report)
    assert check.accepted is False
