"""Video ingestion, validation, and metadata management router.

Compliance and security requirements:
- Rejects hostile/malformed filenames and path traversal attempts.
- Enforces strict size caps (settings.max_upload_size_mb).
- Discards non-video tracks (audio, metadata) and normalizes to constant-framerate H.264.
- Discloses research-use-only policy (P1).
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from surgisight.api.deps import get_current_user, record_access_log
from surgisight.api.routers.media import generate_signed_media_token
from surgisight.contract.types import RESEARCH_DISCLAIMER
from surgisight.data.video import (
    VideoValidationError,
    generate_thumbnail,
    transcode_and_normalize,
)
from surgisight.db import UserModel, VideoModel, get_db
from surgisight.settings import settings

router = APIRouter(prefix="/videos", tags=["videos"])

SAFE_FILENAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


class VideoResponse(BaseModel):
    id: str
    global_video_id: str
    dataset: str
    duration_s: float
    fps: float
    crop_offset: list[int]
    thumbnail_url: str
    media_url: str
    notice: str


def sanitize_filename(filename: str) -> str:
    """Validate and sanitize filename preventing directory traversal and null byte injections."""
    if "\x00" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename contains forbidden null characters.",
        )

    base = os.path.basename(filename)
    if ".." in filename or "/" in base or "\\" in base:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename contains illegal path traversal components.",
        )

    if not SAFE_FILENAME_REGEX.match(base):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename contains illegal characters. Only alphanumeric, dashes, dots, and underscores allowed.",
        )

    return base


@router.post("", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
async def upload_video(
    file: Annotated[UploadFile, File(description="Video file (MP4, MKV, AVI, etc.)")],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
    dataset: Annotated[str, Form(description="Source research dataset name")] = "cholec80",
) -> VideoResponse:
    """Ingest a surgical video file, validate, normalize to H.264, and index in database."""
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided.")

    safe_name = sanitize_filename(file.filename)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in {".mp4", ".mkv", ".avi", ".mov", ".webm"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension '{ext}'. Only research surgical video formats allowed.",
        )

    video_id = str(uuid.uuid4())
    global_video_id = f"{dataset}_{Path(safe_name).stem}_{video_id[:8]}"

    storage_root = Path(settings.storage_dir)
    tmp_dir = storage_root / "tmp"
    videos_dir = storage_root / "videos"
    thumbs_dir = storage_root / "thumbnails"
    for d in (tmp_dir, videos_dir, thumbs_dir):
        d.mkdir(parents=True, exist_ok=True)

    tmp_path = tmp_dir / f"upload_{video_id}{ext}"
    final_video_path = videos_dir / f"{video_id}.mp4"
    thumb_path = thumbs_dir / f"{video_id}.jpg"

    # Stream upload with size cap enforcement
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    bytes_written = 0

    try:
        with open(tmp_path, "wb") as f_out:
            while chunk := await file.read(1024 * 1024):  # 1 MB chunk
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds maximum allowed upload size ({settings.max_upload_size_mb} MB).",
                    )
                f_out.write(chunk)

        # Transcode and normalize to constant-framerate faststart H.264
        meta = transcode_and_normalize(tmp_path, final_video_path)

        # Generate representative thumbnail
        generate_thumbnail(final_video_path, thumb_path, at_second=min(2.0, meta.duration_s / 2))

    except VideoValidationError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err)
        ) from val_err
    finally:
        # Clean up temporary upload file
        if tmp_path.exists():
            tmp_path.unlink()

    # Create VideoModel record
    video_row = VideoModel(
        id=video_id,
        global_video_id=global_video_id,
        dataset=dataset,
        storage_path=str(final_video_path),
        duration_s=meta.duration_s,
        fps=meta.fps,
        crop_offset=meta.crop_offset,
        uploaded_by=current_user.id,
    )
    db.add(video_row)
    db.commit()
    db.refresh(video_row)

    # Audit log entry (P7)
    record_access_log(db, action="upload_video", user_id=current_user.id, video_id=video_id)

    # Generate short-lived signed streaming URL
    token = generate_signed_media_token(video_id=video_id, user_id=current_user.id)
    media_url = f"/media/{video_id}?token={token}"
    thumbnail_url = f"/media/thumbnails/{video_id}.jpg"

    return VideoResponse(
        id=video_row.id,
        global_video_id=video_row.global_video_id,
        dataset=video_row.dataset,
        duration_s=video_row.duration_s,
        fps=video_row.fps,
        crop_offset=video_row.crop_offset,  # type: ignore[arg-type]
        thumbnail_url=thumbnail_url,
        media_url=media_url,
        notice=RESEARCH_DISCLAIMER,
    )


@router.get("/{video_id}", response_model=VideoResponse)
def get_video_details(
    video_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
) -> VideoResponse:
    """Retrieve video details and fresh signed streaming URL."""
    video = db.execute(select(VideoModel).where(VideoModel.id == video_id)).scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found.")

    token = generate_signed_media_token(video_id=video.id, user_id=current_user.id)
    return VideoResponse(
        id=video.id,
        global_video_id=video.global_video_id,
        dataset=video.dataset,
        duration_s=video.duration_s,
        fps=video.fps,
        crop_offset=video.crop_offset,  # type: ignore[arg-type]
        thumbnail_url=f"/media/thumbnails/{video.id}.jpg",
        media_url=f"/media/{video.id}?token={token}",
        notice=RESEARCH_DISCLAIMER,
    )
