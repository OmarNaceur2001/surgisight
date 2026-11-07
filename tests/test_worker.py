"""Tests for Database Job Queue, Pipeline Orchestrator, and Parquet Storage (WP5).

Covers:
- Provider Registry and interfaces
- DB queue claiming and idempotency
- Atomic Parquet storage (1 Hz and 5 Hz streams)
- End-to-end pipeline execution from enqueued run to validated report and search indexes
- Failure isolation per stage
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from surgisight.contract.models import Report
from surgisight.contract.types import RunStatus
from surgisight.db import (
    EventModel,
    PhaseSegmentModel,
    ReportModel,
    UserModel,
    VideoModel,
    init_db,
)
from surgisight.models.providers import (
    PhaseProvider,
    ProviderRegistry,
    ToolPresenceProvider,
)
from surgisight.worker.orchestrator import PipelineOrchestrator, StageExecutionError
from surgisight.worker.queue import claim_next_run, enqueue_analysis_run
from surgisight.worker.storage import (
    read_predictions_parquet,
    save_1hz_predictions_parquet,
)


@pytest.fixture
def worker_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


@pytest.fixture
def sample_video(worker_db: Session) -> VideoModel:
    user = UserModel(email="researcher@lab.org", password_hash="hash", role="researcher")
    worker_db.add(user)
    worker_db.flush()

    video = VideoModel(
        global_video_id="test_pipeline_vid",
        dataset="cholec80",
        storage_path="storage/sample.mp4",
        duration_s=300.0,
        fps=25.0,
        crop_offset=[0, 0, 640, 360],
        uploaded_by=user.id,
    )
    worker_db.add(video)
    worker_db.commit()
    worker_db.refresh(video)
    return video


# ==============================================================================
# 1. Provider Registry Tests
# ==============================================================================


def test_provider_registry_returns_conforming_providers() -> None:
    phase_p = ProviderRegistry.get_phase_provider()
    tool_p = ProviderRegistry.get_tool_provider()
    _det_p = ProviderRegistry.get_detector_provider()
    _track_p = ProviderRegistry.get_tracker_provider()
    _trip_p = ProviderRegistry.get_triplet_provider()

    assert isinstance(phase_p, PhaseProvider)
    assert isinstance(tool_p, ToolPresenceProvider)

    # Validate output of mock providers
    preds, segs = phase_p.predict_phases(duration_s=120.0, seed=1)
    assert len(preds) == 120
    assert len(segs) == 7


# ==============================================================================
# 2. Database Job Queue & Idempotency Tests
# ==============================================================================


def test_queue_enqueue_and_claim(worker_db: Session, sample_video: VideoModel) -> None:
    # 1. Enqueue
    run, created = enqueue_analysis_run(worker_db, video_id=sample_video.id)
    assert created is True
    assert run.status == RunStatus.PENDING.value

    # 2. Idempotency: enqueuing again with identical parameters returns existing run
    run_duplicate, created_again = enqueue_analysis_run(worker_db, video_id=sample_video.id)
    assert created_again is False
    assert run_duplicate.id == run.id

    # 3. Claim run
    claimed = claim_next_run(worker_db, worker_id="test_worker")
    assert claimed is not None
    assert claimed.id == run.id
    assert claimed.status == RunStatus.PROCESSING.value
    assert claimed.started_at is not None

    # 4. Next claim returns None (empty queue)
    empty_claim = claim_next_run(worker_db, worker_id="test_worker")
    assert empty_claim is None


# ==============================================================================
# 3. Parquet Serialization Tests
# ==============================================================================


def test_parquet_atomic_storage(tmp_path: Path, monkeypatch) -> None:
    from surgisight.contract.mock_generator import generate_mock_analysis
    from surgisight.settings import settings

    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    mock_res = generate_mock_analysis(duration_minutes=2.0, seed=42)
    run_id = "test_parquet_run_123"

    # Save
    out_path = save_1hz_predictions_parquet(run_id, mock_res.per_second_records)
    assert os.path.exists(out_path)
    assert out_path.endswith("predictions_1hz.parquet")

    # Read back
    table = read_predictions_parquet(run_id, stream="1hz")
    assert len(table) == 120
    assert "t" in table.column_names
    assert "phase_label" in table.column_names
    assert "tool_Grasper" in table.column_names


# ==============================================================================
# 4. Pipeline Orchestrator End-to-End Execution
# ==============================================================================


def test_pipeline_orchestrator_execution(
    worker_db: Session, sample_video: VideoModel, tmp_path: Path, monkeypatch
) -> None:
    from surgisight.settings import settings

    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    # 1. Enqueue run
    run, _ = enqueue_analysis_run(worker_db, video_id=sample_video.id)

    # 2. Execute orchestrator
    orchestrator = PipelineOrchestrator(worker_db, run.id)
    report = orchestrator.execute()

    assert isinstance(report, Report)
    assert report.duration_s == sample_video.duration_s

    # 3. Verify DB run status updated
    worker_db.refresh(run)
    assert run.status == RunStatus.COMPLETED.value
    assert run.progress == 1.0
    assert run.finished_at is not None

    # 4. Verify ReportModel created
    db_report = worker_db.execute(
        select(ReportModel).where(ReportModel.run_id == run.id)
    ).scalar_one_or_none()
    assert db_report is not None
    assert db_report.status == "DRAFT_PENDING_REVIEW"

    # 5. Verify search indexes populated
    segs = (
        worker_db.execute(select(PhaseSegmentModel).where(PhaseSegmentModel.run_id == run.id))
        .scalars()
        .all()
    )
    assert len(segs) == 7

    events = (
        worker_db.execute(select(EventModel).where(EventModel.run_id == run.id)).scalars().all()
    )
    assert len(events) >= 3

    # 6. Verify Parquet files exist
    assert os.path.exists(tmp_path / "runs" / run.id / "predictions_1hz.parquet")
    assert os.path.exists(tmp_path / "runs" / run.id / "predictions_5hz.parquet")


def test_pipeline_failure_isolation(worker_db: Session, sample_video: VideoModel) -> None:
    """A failing provider stage marks run as FAILED with error detail without crashing DB."""
    run, _ = enqueue_analysis_run(worker_db, video_id=sample_video.id)

    with patch.object(
        ProviderRegistry, "get_phase_provider", side_effect=RuntimeError("GPU OOM / Model crash")
    ):
        orchestrator = PipelineOrchestrator(worker_db, run.id)
        with pytest.raises(StageExecutionError, match="GPU OOM / Model crash"):
            orchestrator.execute()

    worker_db.refresh(run)
    assert run.status == RunStatus.FAILED.value
    assert "GPU OOM / Model crash" in str(run.error)
    assert run.finished_at is not None
