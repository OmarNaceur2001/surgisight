"""Media serving router supporting HTTP range requests and signed URLs (P7).

Features:
- Validates short-lived HMAC/JWT signed URL or Bearer token
- Handles HTTP Range requests (206 Partial Content) for seamless video seeking
- Rejects expired or tampered signatures
- Logs each media streaming access in audit log (P7)
- Returns mandatory research prototype header (P1)
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from surgisight.api.deps import record_access_log
from surgisight.db import VideoModel, get_db
from surgisight.settings import settings

router = APIRouter(tags=["media"])

SIGNED_MEDIA_TYPE = "media_access"


def generate_signed_media_token(
    video_id: str,
    user_id: str | None = None,
    expires_in_seconds: int = 300,
) -> str:
    """Generate a short-lived signed token for media streaming."""
    exp = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
    payload = {
        "sub": user_id or "anonymous_researcher",
        "video_id": video_id,
        "type": SIGNED_MEDIA_TYPE,
        "exp": exp,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_media_token(video_id: str, token: str) -> dict[str, str]:
    """Validate signature and expiration of media token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "video_id", "type"]},
        )
    except jwt.ExpiredSignatureError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Media access token has expired.",
        ) from err
    except jwt.InvalidTokenError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid media access token: {err}",
        ) from err

    if payload.get("type") != SIGNED_MEDIA_TYPE:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type.")
    if payload.get("video_id") != video_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token was not issued for the requested video.",
        )

    return payload


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    """Parse HTTP Range header 'bytes=start-end' into (start, end) offsets."""
    if not range_header.startswith("bytes="):
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Range header must start with 'bytes='",
        )

    range_val = range_header[6:].strip()
    parts = range_val.split("-")
    if len(parts) != 2:
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE)

    start_str, end_str = parts[0].strip(), parts[1].strip()

    if start_str and end_str:
        start = int(start_str)
        end = int(end_str)
    elif start_str and not end_str:
        start = int(start_str)
        end = file_size - 1
    elif not start_str and end_str:
        # Suffix range
        suffix_len = int(end_str)
        start = max(0, file_size - suffix_len)
        end = file_size - 1
    else:
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE)

    if start >= file_size or end >= file_size or start > end:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    return start, end


@router.get("/media/{video_id}")
def stream_media(
    video_id: str,
    db: Annotated[Session, Depends(get_db)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    token: Annotated[str | None, Query(description="Short-lived signed token")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Response:
    """Serve video stream with HTTP range request support (206 Partial Content)."""
    # 1. Verify authorization (either signed token in query or Bearer token in header)
    caller_id = "unknown"
    if token:
        payload = verify_media_token(video_id, token)
        caller_id = payload.get("sub", "token_user")
    elif authorization and authorization.startswith("Bearer "):
        bearer_token = authorization.split(" ")[1]
        try:
            auth_payload = jwt.decode(
                bearer_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
            )
            caller_id = auth_payload.get("sub", "bearer_user")
        except jwt.InvalidTokenError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            ) from err
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Media access requires a signed URL token or Authorization header.",
        )

    # 2. Lookup video
    video = db.execute(select(VideoModel).where(VideoModel.id == video_id)).scalar_one_or_none()
    if not video or not os.path.exists(video.storage_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video media not found.")

    file_path = video.storage_path
    file_size = os.path.getsize(file_path)

    # 3. Audit log (P7)
    record_access_log(db, action="stream_video", user_id=caller_id, video_id=video_id)

    # 4. Handle Range header
    chunk_size = 1024 * 512  # 512 KB chunks

    if range_header:
        start, end = parse_range_header(range_header, file_size)
        content_length = end - start + 1

        def file_iterator():
            with open(file_path, "rb") as f:
                f.seek(start)
                bytes_left = content_length
                while bytes_left > 0:
                    read_len = min(chunk_size, bytes_left)
                    data = f.read(read_len)
                    if not data:
                        break
                    bytes_left -= len(data)
                    yield data

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
            "Content-Type": "video/mp4",
            "X-Research-Notice": "Research prototype -- not for clinical use",
        }
        return StreamingResponse(
            file_iterator(), status_code=status.HTTP_206_PARTIAL_CONTENT, headers=headers
        )

    # Full file delivery
    def full_iterator():
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": "video/mp4",
        "X-Research-Notice": "Research prototype -- not for clinical use",
    }
    return StreamingResponse(full_iterator(), status_code=status.HTTP_200_OK, headers=headers)
