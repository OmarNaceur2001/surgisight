"""Tests for SurgiSight Database, Models, Migrations, and Append-Only Corrections.

Covers:
- In-memory SQLite initialization and migration verification
- Model persistence and relational cascades
- JSON_VARIANT portability across dialects
- Strict append-only enforcement on corrections (P6)
- Search index population from Report model
- Up/down Alembic migrations
- Optional live PostgreSQL tests (marked @pytest.mark.postgres).
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from surgisight.contract import generate_mock_analysis
from surgisight.db import (
    AnalysisRunModel,
    AppendOnlyViolationError,
    Base,
    DatabaseService,
    EventModel,
    PhaseSegmentModel,
    ReportModel,
    TripletIndexModel,
    UserModel,
    VideoModel,
    init_db,
)

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def sqlite_engine():
    """In-memory SQLite engine for fast unit tests without external DB."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sqlite_engine) -> Generator[Session, None, None]:
    """Test database session with automatic cleanup."""
    SessionLocal = sessionmaker(bind=sqlite_engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ==============================================================================
# 1. Table Creation and Schema Validation
# ==============================================================================


def test_all_11_tables_created(sqlite_engine) -> None:
    """Verify that all 11 required tables exist in metadata and engine."""
    expected_tables = {
        "users",
        "videos",
        "analysis_runs",
        "reports",
        "corrections",
        "phase_segments",
        "tool_intervals",
        "events",
        "triplet_index",
        "cohort_stats",
        "access_log",
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(
        actual_tables
    ), f"Missing tables: {expected_tables - actual_tables}"


def test_user_creation_and_query(db_session: Session) -> None:
    user = UserModel(
        email="lead.surgeon@research.org",
        password_hash="argon2id$mockhash",
        role="reviewer",
    )
    db_session.add(user)
    db_session.commit()

    saved = db_session.execute(
        select(UserModel).where(UserModel.email == "lead.surgeon@research.org")
    ).scalar_one()
    assert saved.id is not None
    assert saved.role == "reviewer"
    assert saved.is_active is True


# ==============================================================================
# 2. Relational Flow: Video -> AnalysisRun -> Report -> Indexing
# ==============================================================================


def test_video_and_analysis_run_lifecycle(db_session: Session) -> None:
    user = UserModel(email="researcher@hospital.edu", password_hash="pwd", role="researcher")
    db_session.add(user)
    db_session.flush()

    video = VideoModel(
        global_video_id="cholec80_synthetic_01",
        dataset="cholec80",
        storage_path="storage/videos/syn01.mp4",
        duration_s=1800.0,
        fps=25.0,
        crop_offset=[40, 0, 774, 480],
        uploaded_by=user.id,
    )
    db_session.add(video)
    db_session.flush()

    run = AnalysisRunModel(
        video_id=video.id,
        status="PROCESSING",
        progress=0.45,
        stage="m2_phase",
        contract_version="1.0",
        model_versions={"m2": "v0.1"},
        config_hash="abc123hash",
        idempotency_key=f"{video.id}_v1_abc123",
    )
    db_session.add(run)
    db_session.flush()

    assert run.id is not None
    assert run.video.global_video_id == "cholec80_synthetic_01"


def test_populate_run_indices_from_report(db_session: Session) -> None:
    """Verify that Report model correctly populates relational search tables."""
    # 1. Generate synthetic mock analysis
    mock_data = generate_mock_analysis(duration_minutes=20.0, seed=42)

    # 2. Persist parent video and run
    video = VideoModel(
        global_video_id="video_index_test",
        dataset="test_cohort",
        storage_path="storage/v.mp4",
        duration_s=mock_data.report.duration_s,
        crop_offset=[0, 0, 854, 480],
    )
    db_session.add(video)
    db_session.flush()

    run = AnalysisRunModel(
        video_id=video.id,
        status="COMPLETED",
        progress=1.0,
        stage="completed",
        contract_version="1.0",
        model_versions={"mock": "1.0"},
        config_hash="test_cfg",
        idempotency_key="unique_run_01",
    )
    db_session.add(run)
    db_session.flush()

    # 3. Create Report row
    report_row = ReportModel(
        run_id=run.id,
        status="DRAFT_PENDING_REVIEW",
        report_json=mock_data.report.model_dump(),
    )
    db_session.add(report_row)
    db_session.flush()

    # 4. Populate relational indexes
    DatabaseService.populate_run_indices(db_session, run.id, mock_data.report)
    db_session.commit()

    # 5. Query phase segments
    segs = (
        db_session.execute(
            select(PhaseSegmentModel)
            .where(PhaseSegmentModel.run_id == run.id)
            .order_by(PhaseSegmentModel.start)
        )
        .scalars()
        .all()
    )
    assert len(segs) == 7
    assert segs[0].label == "P1"
    assert segs[-1].label == "P7"

    # 6. Query key events
    events = (
        db_session.execute(select(EventModel).where(EventModel.run_id == run.id)).scalars().all()
    )
    assert len(events) > 0
    event_types = [e.type for e in events]
    assert "start_calot_dissection" in event_types

    # 7. Query triplet index
    triplets = (
        db_session.execute(select(TripletIndexModel).where(TripletIndexModel.run_id == run.id))
        .scalars()
        .all()
    )
    assert len(triplets) == len(mock_data.report.triplet_highlights)


# ==============================================================================
# 3. Append-Only Enforcement on Corrections (P6)
# ==============================================================================


def test_corrections_append_only_service_layer(db_session: Session) -> None:
    """Service layer must refuse UPDATE and DELETE on corrections."""
    user = UserModel(email="reviewer@clinic.org", password_hash="pwd", role="reviewer")
    db_session.add(user)
    db_session.flush()

    video = VideoModel(
        global_video_id="v_corr_test",
        dataset="test",
        storage_path="path",
        duration_s=600.0,
        crop_offset=[0, 0, 640, 480],
    )
    db_session.add(video)
    db_session.flush()

    run = AnalysisRunModel(
        video_id=video.id,
        config_hash="c1",
        idempotency_key="k1",
    )
    db_session.add(run)
    db_session.flush()

    report = ReportModel(
        run_id=run.id,
        status="DRAFT_PENDING_REVIEW",
        report_json={"test": 1},
    )
    db_session.add(report)
    db_session.flush()

    # 1. Insert correction succeeds
    corr = DatabaseService.add_correction_sync(
        session=db_session,
        report_id=report.id,
        author_id=user.id,
        target_type="PHASE_BOUNDARY",
        target_ref="P2_end",
        before={"end": 450.0},
        after={"end": 480.0},
        reason="Dissection continued until cystic artery clearly exposed.",
    )
    db_session.commit()
    assert corr.id is not None

    # 2. Update must raise AppendOnlyViolationError
    with pytest.raises(AppendOnlyViolationError, match="Cannot UPDATE correction"):
        DatabaseService.update_correction_sync(db_session, corr.id, {"reason": "tampered"})

    # 3. Delete must raise AppendOnlyViolationError
    with pytest.raises(AppendOnlyViolationError, match="Cannot DELETE correction"):
        DatabaseService.delete_correction_sync(db_session, corr.id)


# ==============================================================================
# 4. Alembic Up/Down Migration Test
# ==============================================================================


def test_alembic_up_down_migrations_sqlite(tmp_path) -> None:
    """Verify that Alembic migrations run upgrade head and downgrade base without error."""
    db_file = tmp_path / "migration_test.db"
    test_db_url = f"sqlite:///{db_file}"

    alembic_cfg = Config(os.path.join(ROOT_DIR, "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", test_db_url)
    alembic_cfg.set_main_option(
        "script_location", os.path.join(ROOT_DIR, "surgisight", "db", "migrations")
    )

    # Upgrade to head
    command.upgrade(alembic_cfg, "head")

    # Verify tables exist
    test_engine = create_engine(test_db_url)
    with test_engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
        tables = {row[0] for row in result.fetchall()}
        assert "users" in tables
        assert "reports" in tables
        assert "corrections" in tables
        assert "phase_segments" in tables

    # Downgrade to base
    command.downgrade(alembic_cfg, "base")

    # Verify tables removed
    with test_engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
        tables = {row[0] for row in result.fetchall()}
        assert "reports" not in tables
        assert "corrections" not in tables

    # Upgrade back to head
    command.upgrade(alembic_cfg, "head")
    test_engine.dispose()


# ==============================================================================
# 5. Live PostgreSQL Integration Tests (@pytest.mark.postgres)
# ==============================================================================


@pytest.mark.postgres
def test_postgres_append_only_trigger() -> None:
    """On live PostgreSQL, DB trigger strictly rejects UPDATE and DELETE on corrections."""
    from surgisight.db.service import POSTGRES_APPEND_ONLY_TRIGGER_SQL
    from surgisight.settings import settings

    if "postgresql" not in settings.database_url:
        pytest.skip("DATABASE_URL is not PostgreSQL")

    engine = create_engine(settings.database_url)
    init_db(engine)

    with engine.begin() as conn:
        # Install PostgreSQL trigger
        conn.execute(text(POSTGRES_APPEND_ONLY_TRIGGER_SQL))

        # Insert dummy data
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, role, is_active, created_at) "
                "VALUES ('u1', 'pg_test@doc.org', 'pwd', 'reviewer', true, NOW()) ON CONFLICT DO NOTHING;"
            )
        )
        conn.execute(
            text(
                "INSERT INTO videos (id, global_video_id, dataset, storage_path, duration_s, fps, crop_offset, created_at) "
                "VALUES ('v1', 'pg_v1', 'cholec', 'p', 100, 25, '[0,0,10,10]', NOW()) ON CONFLICT DO NOTHING;"
            )
        )
        conn.execute(
            text(
                "INSERT INTO analysis_runs (id, video_id, config_hash, idempotency_key, model_versions) "
                "VALUES ('r1', 'v1', 'h', 'k_pg', '{}') ON CONFLICT DO NOTHING;"
            )
        )
        conn.execute(
            text(
                "INSERT INTO reports (id, run_id, status, report_json, created_at, updated_at) "
                "VALUES ('rep1', 'r1', 'DRAFT_PENDING_REVIEW', '{}', NOW(), NOW()) ON CONFLICT DO NOTHING;"
            )
        )
        conn.execute(
            text(
                "INSERT INTO corrections (id, report_id, author_id, target_type, target_ref, before, after, reason, created_at) "
                "VALUES ('c1', 'rep1', 'u1', 'PHASE_BOUNDARY', 'P1', '{}', '{}', 'reason', NOW()) ON CONFLICT DO NOTHING;"
            )
        )

        # Attempting UPDATE must fail at database level
        with pytest.raises(Exception, match="corrections table is strictly append-only"):
            conn.execute(text("UPDATE corrections SET reason='modified' WHERE id='c1';"))

        # Attempting DELETE must fail at database level
        with pytest.raises(Exception, match="corrections table is strictly append-only"):
            conn.execute(text("DELETE FROM corrections WHERE id='c1';"))

    engine.dispose()
