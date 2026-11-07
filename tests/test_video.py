"""Tests for Video processing, black border crop, transforms, and media streaming (WP4).

Covers:
- Black border detection on synthetic frames
- Canonical frame_transform (size, normalization, channels-first)
- Synthetic video fixture creation and PyAV probing
- Frame extraction at 1 FPS and 5 FPS
- Video upload endpoint (size cap, hostile filename rejection, normalization)
- Media streaming endpoint with HTTP Range requests (206 Partial Content)
- Short-lived signed URL validation and expiration
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from surgisight.api.auth import create_access_token
from surgisight.api.main import app
from surgisight.api.routers.media import generate_signed_media_token
from surgisight.data.transforms import detect_black_borders, frame_transform
from surgisight.data.video import (
    extract_frames,
    generate_synthetic_video,
    generate_thumbnail,
    probe_video,
)
from surgisight.db import AccessLogModel, UserModel, VideoModel, get_db, init_db


@pytest.fixture
def video_db():
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
def client(video_db: Session) -> TestClient:
    def override_get_db():
        try:
            yield video_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def synthetic_video_path(tmp_path: Path) -> str:
    """Generate a 2-second synthetic MP4 video fixture with synthetic black borders."""
    video_file = tmp_path / "test_cholec.mp4"
    return generate_synthetic_video(
        output_path=video_file,
        duration_s=2.0,
        fps=25.0,
        width=640,
        height=360,
        black_border_px=30,
    )


# ==============================================================================
# 1. Transforms and Black-Border Crop Tests
# ==============================================================================


def test_detect_black_borders_with_border() -> None:
    # 360 x 640 frame with 40px black borders around a bright center
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    frame[40:320, 40:600] = 180  # bright center

    crop = detect_black_borders(frame, luminance_threshold=15.0)
    assert len(crop) == 4
    x, y, w, h = crop
    assert abs(x - 40) <= 2
    assert abs(y - 40) <= 2
    assert abs(w - 560) <= 4
    assert abs(h - 280) <= 4


def test_detect_black_borders_no_border() -> None:
    # Entire frame is illuminated
    frame = np.full((360, 640, 3), fill_value=200, dtype=np.uint8)
    crop = detect_black_borders(frame)
    assert crop == [0, 0, 640, 360]


def test_frame_transform_output_shape_and_range() -> None:
    frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
    crop_offset = [20, 10, 600, 460]

    tensor = frame_transform(frame, crop_offset=crop_offset, target_size=(224, 224), normalize=True)

    # Output must be (Channels, Height, Width) -> (3, 224, 224)
    assert tensor.shape == (3, 224, 224)
    assert tensor.dtype == np.float32

    # Verify deterministic output
    tensor_repeat = frame_transform(
        frame, crop_offset=crop_offset, target_size=(224, 224), normalize=True
    )
    np.testing.assert_array_equal(tensor, tensor_repeat)


# ==============================================================================
# 2. PyAV Video Probing and Frame Extraction
# ==============================================================================


def test_probe_synthetic_video(synthetic_video_path: str) -> None:
    meta = probe_video(synthetic_video_path)
    assert meta.fps == 25.0
    assert meta.duration_s >= 1.9
    assert meta.width == 640
    assert meta.height == 360
    assert len(meta.crop_offset) == 4
    assert meta.frame_count >= 48


def test_extract_frames_1hz_and_5hz(synthetic_video_path: str) -> None:
    # 1 FPS extraction over 2-second video -> ~2 frames
    frames_1hz = list(extract_frames(synthetic_video_path, fps_target=1.0))
    assert len(frames_1hz) in (2, 3)
    t, f_idx, img = frames_1hz[0]
    assert t == 0.0
    assert img.ndim == 3

    # 5 FPS extraction -> ~10 frames
    frames_5hz = list(extract_frames(synthetic_video_path, fps_target=5.0))
    assert len(frames_5hz) >= 9


def test_generate_thumbnail(synthetic_video_path: str, tmp_path: Path) -> None:
    thumb_out = tmp_path / "thumb.jpg"
    out_file = generate_thumbnail(synthetic_video_path, thumb_out, at_second=0.5)
    assert os.path.exists(out_file)
    assert os.path.getsize(out_file) > 1000


# ==============================================================================
# 3. Video Upload Endpoint (POST /videos)
# ==============================================================================


def test_upload_video_success(
    client: TestClient, video_db: Session, synthetic_video_path: str
) -> None:
    user = UserModel(
        email="uploader@hospital.org", password_hash="pwd", role="researcher", is_active=True
    )
    video_db.add(user)
    video_db.commit()
    auth_token = create_access_token(user_id=user.id, role=user.role)

    with open(synthetic_video_path, "rb") as vf:
        video_bytes = vf.read()

    res = client.post(
        "/videos",
        files={"file": ("procedure_01.mp4", io.BytesIO(video_bytes), "video/mp4")},
        data={"dataset": "cholec80_val"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    assert res.status_code == 201
    data = res.json()
    assert "id" in data
    assert data["dataset"] == "cholec80_val"
    assert data["duration_s"] >= 1.9
    assert "not for clinical use" in data["notice"].lower()
    assert data["media_url"].startswith("/media/")

    # Check database record
    db_video = video_db.execute(
        select(VideoModel).where(VideoModel.id == data["id"])
    ).scalar_one_or_none()
    assert db_video is not None
    assert db_video.duration_s >= 1.9


def test_upload_video_hostile_filenames(client: TestClient, video_db: Session) -> None:
    user = UserModel(email="user@test.org", password_hash="pwd", role="researcher", is_active=True)
    video_db.add(user)
    video_db.commit()
    auth_token = create_access_token(user_id=user.id, role=user.role)

    # Hostile path traversal attempt
    res = client.post(
        "/videos",
        files={"file": ("../../etc/passwd.mp4", io.BytesIO(b"fake"), "video/mp4")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert res.status_code == 400
    assert "path traversal" in res.json()["detail"].lower()

    # Null byte attempt
    res = client.post(
        "/videos",
        files={"file": ("innocent.mp4\x00.exe", io.BytesIO(b"fake"), "video/mp4")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert res.status_code == 400


def test_upload_video_invalid_format(client: TestClient, video_db: Session) -> None:
    user = UserModel(email="user2@test.org", password_hash="pwd", role="researcher", is_active=True)
    video_db.add(user)
    video_db.commit()
    auth_token = create_access_token(user_id=user.id, role=user.role)

    res = client.post(
        "/videos",
        files={"file": ("malware.exe", io.BytesIO(b"dummy"), "application/octet-stream")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert res.status_code == 400
    assert "Unsupported file extension" in res.json()["detail"]


# ==============================================================================
# 4. Media Streaming & HTTP Range Requests (GET /media/{video_id})
# ==============================================================================


def test_media_streaming_full_and_range_requests(
    client: TestClient, video_db: Session, synthetic_video_path: str
) -> None:
    # 1. Register video in database
    video_id = "test_stream_video_uuid"
    video_row = VideoModel(
        id=video_id,
        global_video_id="video_stream_01",
        dataset="cholec80",
        storage_path=synthetic_video_path,
        duration_s=2.0,
        fps=25.0,
        crop_offset=[0, 0, 640, 360],
    )
    video_db.add(video_row)
    video_db.commit()

    file_size = os.path.getsize(synthetic_video_path)
    signed_token = generate_signed_media_token(video_id=video_id, expires_in_seconds=300)

    # 2. Full request (without Range header) -> HTTP 200
    res_full = client.get(f"/media/{video_id}?token={signed_token}")
    assert res_full.status_code == 200
    assert len(res_full.content) == file_size
    assert res_full.headers["Accept-Ranges"] == "bytes"
    assert "not for clinical use" in res_full.headers["X-Research-Notice"].lower()

    # 3. Range request: first 500 bytes -> HTTP 206 Partial Content
    res_range = client.get(
        f"/media/{video_id}?token={signed_token}",
        headers={"Range": "bytes=0-499"},
    )
    assert res_range.status_code == 206
    assert len(res_range.content) == 500
    assert res_range.headers["Content-Range"] == f"bytes 0-499/{file_size}"
    assert res_range.headers["Content-Length"] == "500"

    # 4. Range request: suffix/tail range
    res_tail = client.get(
        f"/media/{video_id}?token={signed_token}",
        headers={"Range": f"bytes={file_size - 100}-"},
    )
    assert res_tail.status_code == 206
    assert len(res_tail.content) == 100

    # 5. Verify audit log entry was created
    audit = (
        video_db.execute(select(AccessLogModel).where(AccessLogModel.video_id == video_id))
        .scalars()
        .all()
    )
    assert len(audit) >= 3


def test_media_streaming_invalid_or_expired_token(client: TestClient, video_db: Session) -> None:
    # No token or header -> 401
    res = client.get("/media/any_video")
    assert res.status_code == 401

    # Tampered token -> 401
    valid_token = generate_signed_media_token(video_id="v1")
    tampered = valid_token[:-4] + "fake"
    res_tampered = client.get(f"/media/v1?token={tampered}")
    assert res_tampered.status_code == 401

    # Token for different video -> 403
    token_v1 = generate_signed_media_token(video_id="v1")
    res_wrong_vid = client.get(f"/media/v2?token={token_v1}")
    assert res_wrong_vid.status_code == 403
