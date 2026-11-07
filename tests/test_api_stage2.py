"""WP11 endpoint tests use only SQLite synthetic report fixtures."""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from surgisight.api.auth import create_access_token
from surgisight.api.main import app
from surgisight.contract.mock_generator import generate_mock_analysis
from surgisight.contract.types import ReportStatus
from surgisight.db import (
    AnalysisRunModel,
    ReportModel,
    UserModel,
    VideoModel,
    get_db,
    init_db,
)


def test_report_summary_is_generated_from_report_json_and_stored():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    user = UserModel(
        email=f"stage2-{uuid4()}@test.invalid",
        password_hash="not-used",
        role="viewer",
    )
    db.add(user)
    db.flush()
    video = VideoModel(
        global_video_id=f"synthetic-{uuid4()}",
        dataset="synthetic-fixture",
        storage_path="not-a-real-file",
        duration_s=1200.0,
        fps=25.0,
        crop_offset=[0, 0, 224, 224],
        uploaded_by=user.id,
    )
    db.add(video)
    db.flush()
    run = AnalysisRunModel(
        video_id=video.id,
        config_hash="stage2-fixture",
        idempotency_key=f"stage2-{uuid4()}",
        status="COMPLETED",
    )
    db.add(run)
    db.flush()
    generated = generate_mock_analysis(duration_minutes=20, seed=77).report
    source_report = generated.model_copy(
        update={"video_id": video.id, "dataset": video.dataset}
    )
    report = ReportModel(
        run_id=run.id,
        status=ReportStatus.DRAFT_PENDING_REVIEW.value,
        report_json=source_report.model_dump(mode="json"),
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = client.post(f"/reports/{report.id}/summary", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["label"] == "AI-generated"
        assert payload["valid"] is True
        assert payload["checked_numeric_tokens"] > 0

        stored = client.get(f"/reports/{report.id}", headers=headers)
        assert stored.status_code == 200
        assert stored.json()["summary"] == payload["summary"]

        locked = client.post(f"/reports/{report.id}/review", headers=headers)
        assert locked.status_code == 403
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_cohort_and_latency_endpoints_return_aggregates_only():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    user = UserModel(
        email=f"metrics-{uuid4()}@test.invalid",
        password_hash="not-used",
        role="viewer",
    )
    db.add(user)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        cohort = client.get("/cohort/stats", headers=headers)
        metrics = client.get("/metrics/latency", headers=headers)
        assert cohort.status_code == 200
        assert cohort.json()["items"] == []
        assert "notice" in cohort.json()
        assert metrics.status_code == 200
        assert "stages" in metrics.json()
        assert "scope" in metrics.json()
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()
