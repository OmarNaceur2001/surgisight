"""WP9 API tests using in-memory SQLite and synthetic fixtures only."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from surgisight.api.auth import create_access_token
from surgisight.api.main import app
from surgisight.contract.mock_generator import generate_mock_analysis
from surgisight.contract.models import PerSecondRecord, PhasePrediction, ProducerInfo, ToolPresencePrediction
from surgisight.contract.types import PHASE_ORDER, TOOL_ORDER, PhaseId, ReportStatus
from surgisight.db import AnalysisRunModel, ReportModel, UserModel, VideoModel, get_db, init_db
from surgisight.settings import settings
from surgisight.worker.storage import save_1hz_predictions_parquet


@pytest.fixture
def api_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def api_client(api_db):
    def override_db():
        yield api_db
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def _seed_video(api_db, duration_s: float = 120.0):
    """Create a video record and researcher account without media bytes."""
    user = UserModel(email=f"researcher-{uuid4()}@test.invalid", password_hash="not-used", role="researcher")
    api_db.add(user)
    api_db.flush()
    video = VideoModel(
        global_video_id=f"fixture-{uuid4()}", dataset="synthetic-fixture",
        storage_path="not-a-real-file", duration_s=duration_s, fps=25.0,
        crop_offset=[0, 0, 224, 224], uploaded_by=user.id,
    )
    api_db.add(video)
    api_db.commit()
    api_db.refresh(video)
    return video, user


def test_analysis_submission_is_idempotent(api_client, api_db):
    video, user = _seed_video(api_db)
    token = create_access_token(user_id=user.id, role=user.role)
    payload = {"model_versions": {"M2": "mock"}, "config_hash": "fixture"}
    headers = {"Authorization": f"Bearer {token}"}
    first = api_client.post(f"/videos/{video.id}/analyses", json=payload, headers=headers)
    second = api_client.post(f"/videos/{video.id}/analyses", json=payload, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]


def test_analysis_status_requires_auth(api_client, api_db):
    video, _ = _seed_video(api_db)
    run = AnalysisRunModel(video_id=video.id, config_hash="fixture", idempotency_key=f"fixture-{uuid4()}", status="PENDING")
    api_db.add(run)
    api_db.commit()
    assert api_client.get(f"/analyses/{run.id}").status_code == 401


def test_report_json_pdf_corrections_and_review_roles(api_client, api_db):
    video, researcher = _seed_video(api_db)
    reviewer = UserModel(email=f"reviewer-{uuid4()}@test.invalid", password_hash="x", role="reviewer")
    api_db.add(reviewer)
    run = AnalysisRunModel(video_id=video.id, config_hash="fixture", idempotency_key=f"fixture-{uuid4()}", status="COMPLETED")
    api_db.add(run)
    api_db.flush()
    generated = generate_mock_analysis(duration_minutes=20.0, seed=17).report
    report_json = generated.model_copy(update={"video_id": video.id, "dataset": video.dataset}).model_dump(mode="json")
    report_row = ReportModel(run_id=run.id, report_json=report_json, status=ReportStatus.DRAFT_PENDING_REVIEW.value)
    api_db.add(report_row)
    api_db.commit()
    api_db.refresh(report_row)

    researcher_headers = {"Authorization": f"Bearer {create_access_token(user_id=researcher.id, role=researcher.role)}"}
    reviewer_headers = {"Authorization": f"Bearer {create_access_token(user_id=reviewer.id, role=reviewer.role)}"}
    assert api_client.get(f"/reports/{report_row.id}", headers=researcher_headers).status_code == 200
    pdf = api_client.get(f"/reports/{report_row.id}/pdf", headers=researcher_headers)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    correction = {
        "target_type": "REPORT_NOTE", "target_ref": "phase-description",
        "before": {"note": "pending"}, "after": {"note": "updated"},
        "reason": "Clarify the recorded phase description.",
    }
    added = api_client.post(f"/reports/{report_row.id}/corrections", json=correction, headers=researcher_headers)
    assert added.status_code == 201
    assert len(api_client.get(f"/reports/{report_row.id}/corrections", headers=researcher_headers).json()) == 1
    assert api_client.post(f"/reports/{report_row.id}/review", headers=researcher_headers).status_code == 403
    reviewed = api_client.post(f"/reports/{report_row.id}/review", headers=reviewer_headers)
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "REVIEWED"
    blocked = api_client.post(f"/reports/{report_row.id}/corrections", json=correction, headers=reviewer_headers)
    assert blocked.status_code == 409


def test_library_filter_and_pagination(api_client, api_db):
    video, user = _seed_video(api_db)
    token = create_access_token(user_id=user.id, role=user.role)
    response = api_client.get("/videos?phase=P1&limit=10", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_prediction_slice_returns_bounded_records(api_client, api_db, tmp_path, monkeypatch):
    video, user = _seed_video(api_db)
    run = AnalysisRunModel(video_id=video.id, config_hash="fixture", idempotency_key=f"fixture-{uuid4()}", status="COMPLETED")
    api_db.add(run)
    api_db.commit()
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    records = []
    for second in range(5):
        phase = PhaseId.P1
        records.append(PerSecondRecord(
            producer=ProducerInfo(name="fixture", version="1"),
            t=float(second), frame_idx=second * 25,
            phase=PhasePrediction(label=phase, probs={p: (1.0 if p == phase else 0.0) for p in PHASE_ORDER}),
            tools=ToolPresencePrediction(probs={tool: 0.0 for tool in TOOL_ORDER}),
        ))
    save_1hz_predictions_parquet(run.id, records)
    token = create_access_token(user_id=user.id, role=user.role)
    response = api_client.get(
        f"/analyses/{run.id}/predictions?stream=1hz&from=1&to=3&limit=2",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert [r["t"] for r in response.json()["records"]] == [1.0, 2.0]



def test_tool_interval_hysteresis_uses_1hz_probabilities():
    """Search indexes are true probability-derived intervals, not cumulative-duration placeholders."""
    from surgisight.db.service import derive_tool_intervals

    samples = []
    values = [0.1, 0.7, 0.55, 0.35, 0.45, 0.1]
    for value in values:
        probabilities = {tool: 0.0 for tool in TOOL_ORDER}
        probabilities[TOOL_ORDER[0]] = value
        samples.append(ToolPresencePrediction(probs=probabilities))

    intervals = derive_tool_intervals(samples)
    assert intervals["Grasper"] == [(1.0, 3.0)]
    assert all(intervals[tool.value] == [] for tool in TOOL_ORDER[1:])
