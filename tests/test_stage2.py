"""Stage 2 tests use synthetic reports, generated frames, and in-memory metrics only."""
from __future__ import annotations

import asyncio

import numpy as np

from surgisight.analytics.cvs import MockCVSProvider
from surgisight.analytics.latency import LatencyRegistry
from surgisight.analytics.summary import fact_check_summary, generate_grounded_summary
from surgisight.contract.mock_generator import generate_mock_analysis
from surgisight.models.m2_phase.online import OnlinePhasePipeline
from surgisight.worker.streaming import iter_online_replay


def test_generated_summary_is_grounded_in_report_fields():
    report = generate_mock_analysis(duration_minutes=20, seed=32).report
    summary, check = generate_grounded_summary(report)
    assert check.valid
    assert "AI-generated" in summary
    assert report.video_id not in summary
    assert len(summary) > 100


def test_summary_checker_rejects_unlisted_numbers_and_evaluative_terms():
    report = generate_mock_analysis(duration_minutes=20, seed=33).report
    unsupported = fact_check_summary(
        "This record contains 987654 seconds and a poor description.",
        report,
    )
    assert not unsupported.valid
    assert any("Unsupported numeric value" in reason for reason in unsupported.reasons)
    assert any("principle p3" in reason.lower() for reason in unsupported.reasons)


def test_summary_checker_rejects_phase_absent_from_source():
    report = generate_mock_analysis(duration_minutes=20, seed=34).report
    modified = report.model_copy(
        update={"phases": [phase for phase in report.phases if phase.label.value != "P7"]}
    )
    check = fact_check_summary("Observed phase P7.", modified)
    assert not check.valid
    assert any("absent" in reason for reason in check.reasons)


def test_latency_registry_is_bounded_and_reports_percentiles():
    registry = LatencyRegistry(max_samples=3)
    for value in (10, 20, 30, 40):
        registry.record("m2", value)
    result = registry.snapshot()["m2"]
    assert result["count"] == 3
    assert result["p50_ms"] == 30
    assert result["p95_ms"] == 40


def test_cvs_mock_is_explicitly_not_assessed():
    result = MockCVSProvider().assess(["synthetic-frame-1"])
    assert result["status"] == "not_assessed"
    assert result["evidence_refs"] == ["synthetic-frame-1"]


def test_online_replay_calls_same_pipeline_step_and_keeps_buffer_bounded():
    pipeline = OnlinePhasePipeline(config={"feature_dim": 64}, max_buffer_size=2)
    frames = [
        (0.0, 0, np.full((224, 224, 3), 60, dtype=np.uint8)),
        (1.0, 25, np.full((224, 224, 3), 90, dtype=np.uint8)),
        (2.0, 50, np.full((224, 224, 3), 120, dtype=np.uint8)),
    ]

    async def collect():
        return [item async for item in iter_online_replay("synthetic-run", frames, pipeline, speed=8.0)]

    messages = asyncio.run(collect())
    assert len(messages) == 3
    assert [item.record.t for item in messages] == [0.0, 1.0, 2.0]
    assert pipeline.get_buffer_size() == 2
    assert messages[-1].record.phase.label.value in {"P1", "P2", "P3", "P4", "P5", "P6", "P7"}



def test_summary_checker_rejects_unlisted_event_marker():
    report = generate_mock_analysis(duration_minutes=20, seed=35).report
    check = fact_check_summary(
        "Recorded event markers: invented_milestone at 12.00 seconds. Triplet highlights: none.",
        report,
    )
    assert not check.valid
    assert any("Event invented_milestone is absent" in reason for reason in check.reasons)
