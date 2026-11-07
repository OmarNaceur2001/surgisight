"""REST integration tests for analysis and report endpoints (synthetic fixtures only)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from surgisight.api.auth import create_access_token
from surgisight.api.main import app
from surgisight.contract import generate_mock_analysis
from surgisight.db import AnalysisRunModel, ReportModel, UserModel, VideoModel, get_db, init_db


@pytest.fixture
def api_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


@pytest.fixture
def api_client(api_db: Session):
    def override_get_db():
        yield api_db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def seed_report(api_db: Session, role: str = "researcher"):
    user = UserModel(email=f"{role}@example.test", password_hash="fixture", role=role)
    api_db.add(user)
    video = VideoModel(
        global_video_id=f"fixture-{role}",
        dataset="synthetic_fixture",
        storage_path="not-a-real-file",
        duration_s=1200.0,
        fps=25.0,
        crop_offset=[0, 0, 640, 480],
    )
    api_db.add(video)
    api_db.flush()
    run = AnalysisRunModel(
        video_id=video.id,
        status="COMPLETED",
        progress=1.0,
        stage="completed",
        contract_version="1.0",
        model_versions={"M2": "mock-fixture"},
        config_hash="fixture",
        idempotency_key=f"fixture-{role}",
    )
    api_db.add(run)
    mock = generate_mock_analysis(duration_minutes=20.0, seed=11).report
    report = ReportModel(
        run_id=run.id,
        status=mock.status.value,
        report_json=mock.model_dump(mode="json"),
    )
    api_db.add(report)
    api_db.commit()
    return user, video, run, report


def auth_header(user: UserModel) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


def test_report_json_is_returned_from_persisted_contract(api_client, api_db: Session):
    user, _, _, report = seed_report(api_db)
    response = api_client.get(f"/reports/{report.id}", headers=auth_header(user))
    assert response.status_code == 200
    body = response.json()
    assert body["video_id"] == report.report_json["video_id"]
    assert body["disclaimer"] == "Research prototype — not for clinical use"


def test_researcher_can_append_correction_but_cannot_review(api_client, api_db: Session):
    user, _, _, report = seed_report(api_db, "researcher")
    payload = {
        "target_type": "PHASE_BOUNDARY",
        "target_ref": "P2_end",
        "before": {"end": 300.0},
        "after": {"end": 305.0},
        "reason": "The observed transition is visible at the later timestamp.",
    }
    correction = api_client.post(
        f"/reports/{report.id}/corrections", json=payload, headers=auth_header(user)
    )
    assert correction.status_code == 201
    review = api_client.post(
        f"/reports/{report.id}/review", json={"status": "REVIEWED"},
        headers=auth_header(user),
    )
    assert review.status_code == 403


def test_reviewer_can_mark_draft_report_reviewed(api_client, api_db: Session):
    user, _, _, report = seed_report(api_db, "reviewer")
    response = api_client.post(
        f"/reports/{report.id}/review", json={"status": "REVIEWED"},
        headers=auth_header(user),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REVIEWED"
    api_db.refresh(report)
    assert report.status == "REVIEWED"


def test_report_pdf_is_rendered_from_report_row(api_client, api_db: Session):
    user, _, _, report = seed_report(api_db)
    response = api_client.get(f"/reports/{report.id}/pdf", headers=auth_header(user))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content.startswith(b"%PDF-")
