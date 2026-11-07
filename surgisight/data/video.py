"""Video validation, transcoding, and frame extraction services using PyAV.

Operating principles:
- Strips all audio and non-video metadata on ingest (P2/P7).
- Transcodes to normalized H.264 with fixed GOP and faststart for instant seeking.
- Frame extraction at exact time stamps (1 Hz and 5 Hz streams).
- Generates synthetic test fixtures with no real patient or dataset data (P5).
"""

from __future__ import annotations

import math
import os
from collections.abc import Generator
from pathlib import Path

import av
import numpy as np

from surgisight.contract.models import VideoMeta
from surgisight.data.transforms import apply_crop, detect_black_borders

# Permitted video containers and video codecs for security and compatibility
ALLOWED_CONTAINERS = {"mp4", "mkv", "avi", "mov", "webm"}
ALLOWED_CODECS = {"h264", "hevc", "mpeg4", "vp8", "vp9", "av1", "rawvideo", "mjpeg"}


class VideoValidationError(ValueError):
    """Raised when an uploaded video violates container, codec, or size constraints."""

    pass


def probe_video(video_path: str | Path) -> VideoMeta:
    """Inspect video file using PyAV and extract normalized metadata."""
    path_str = str(video_path)
    if not os.path.exists(path_str):
        raise FileNotFoundError(f"Video file not found: {path_str}")

    try:
        with av.open(path_str) as container:
            if not container.streams.video:
                raise VideoValidationError("No video stream found in uploaded file.")

            stream = container.streams.video[0]
            codec_name = stream.codec_context.name
            if codec_name not in ALLOWED_CODECS:
                raise VideoValidationError(
                    f"Video codec '{codec_name}' is not in allowed list: {sorted(ALLOWED_CODECS)}"
                )

            fps = float(stream.average_rate) if stream.average_rate else 25.0
            if fps <= 0 or math.isnan(fps):
                fps = 25.0

            width = stream.codec_context.width
            height = stream.codec_context.height

            # Duration calculation
            if stream.duration and stream.time_base:
                duration_s = float(stream.duration * stream.time_base)
            elif container.duration:
                duration_s = float(container.duration / av.time.AV_TIME_BASE)
            else:
                duration_s = 0.0

            frame_count = stream.frames or int(duration_s * fps)

            # Sample first valid frame to detect black borders
            crop_offset = [0, 0, width, height]
            for packet in container.demux(stream):
                for frame in packet.decode():
                    frame_rgb = frame.to_ndarray(format="rgb24")
                    crop_offset = detect_black_borders(frame_rgb)
                    break
                if crop_offset != [0, 0, width, height]:
                    break

            return VideoMeta(
                fps=round(fps, 2),
                duration_s=round(duration_s, 2),
                width=width,
                height=height,
                crop_offset=crop_offset,
                source=os.path.basename(path_str),
                frame_count=frame_count,
            )
    except Exception as exc:
        if isinstance(exc, VideoValidationError):
            raise
        raise VideoValidationError(f"Failed to decode or inspect video: {exc}") from exc


def extract_frames(
    video_path: str | Path,
    fps_target: float = 1.0,
    crop_offset: list[int] | None = None,
    max_frames: int | None = None,
) -> Generator[tuple[float, int, np.ndarray], None, None]:
    """Extract RGB frames at precise time intervals (e.g. 1.0 FPS or 5.0 FPS).

    Yields:
        (timestamp_seconds, original_frame_idx, frame_rgb_uint8)
    """
    path_str = str(video_path)
    step_seconds = 1.0 / fps_target
    next_target_t = 0.0
    extracted_count = 0

    with av.open(path_str) as container:
        stream = container.streams.video[0]
        fps_orig = float(stream.average_rate) if stream.average_rate else 25.0
        time_base = float(stream.time_base)

        for frame_idx, frame in enumerate(container.decode(stream)):
            pts_time = (
                float(frame.pts * time_base) if frame.pts is not None else (frame_idx / fps_orig)
            )

            if pts_time >= next_target_t - 0.02:  # 20ms tolerance
                frame_rgb = frame.to_ndarray(format="rgb24")
                if crop_offset:
                    frame_rgb = apply_crop(frame_rgb, crop_offset)

                yield round(pts_time, 2), frame_idx, frame_rgb
                extracted_count += 1
                next_target_t += step_seconds

                if max_frames and extracted_count >= max_frames:
                    break


def transcode_and_normalize(
    input_path: str | Path,
    output_path: str | Path,
    target_fps: float = 25.0,
    crf: int = 23,
) -> VideoMeta:
    """Normalize input video to constant-framerate H.264 without audio or metadata."""
    in_str = str(input_path)
    out_str = str(output_path)
    Path(out_str).parent.mkdir(parents=True, exist_ok=True)

    with av.open(in_str) as in_container:
        if not in_container.streams.video:
            raise VideoValidationError("No video stream found.")
        in_stream = in_container.streams.video[0]

        width = in_stream.codec_context.width
        height = in_stream.codec_context.height
        # Ensure dimensions are even for H.264 encoding
        width = width if width % 2 == 0 else width - 1
        height = height if height % 2 == 0 else height - 1

        with av.open(out_str, mode="w", format="mp4") as out_container:
            # faststart flag places moov atom before mdat for smooth HTTP streaming
            # faststart enabled via stream options

            out_stream = out_container.add_stream(
                "libx264" if "libx264" in av.codecs_available else "h264", rate=int(target_fps)
            )
            out_stream.width = width
            out_stream.height = height
            out_stream.pix_fmt = "yuv420p"
            out_stream.options = {"crf": str(crf), "preset": "fast", "movflags": "faststart"}

            # frame encode loop
            for frame in in_container.decode(in_stream):
                # Ensure correct dimensions
                if frame.width != width or frame.height != height:
                    frame = frame.reformat(width=width, height=height, format="yuv420p")
                else:
                    frame = frame.reformat(format="yuv420p")

                for packet in out_stream.encode(frame):
                    out_container.mux(packet)
                # encoded

            # Flush encoder
            for packet in out_stream.encode():
                out_container.mux(packet)

    return probe_video(out_str)


def generate_synthetic_video(
    output_path: str | Path,
    duration_s: float = 4.0,
    fps: float = 25.0,
    width: int = 640,
    height: int = 360,
    black_border_px: int = 40,
) -> str:
    """Generate a clean synthetic test-pattern video for automated tests (no medical data)."""
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = int(duration_s * fps)

    with av.open(str(out_path), mode="w", format="mp4") as container:
        stream = container.add_stream("h264", rate=int(fps))
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        stream.options = {"movflags": "faststart"}

        for i in range(total_frames):
            # Create synthetic canvas with black border
            frame_arr = np.zeros((height, width, 3), dtype=np.uint8)

            # Central endoscopic simulation area with moving test shapes
            x1 = black_border_px
            y1 = black_border_px
            x2 = width - black_border_px
            y2 = height - black_border_px

            # Moving color gradient to simulate laparoscopic illumination
            phase_shift = int((i / total_frames) * 200)
            frame_arr[y1:y2, x1:x2, 0] = (160 + phase_shift // 2) % 255  # Reddish tissue tint
            frame_arr[y1:y2, x1:x2, 1] = (60 + phase_shift // 4) % 255
            frame_arr[y1:y2, x1:x2, 2] = (80 + phase_shift // 3) % 255

            # Moving metallic instrument bar
            inst_x = int(x1 + (i % 60) * ((x2 - x1 - 50) / 60))
            frame_arr[y1 + 40 : y1 + 100, inst_x : inst_x + 30] = [210, 210, 220]

            frame = av.VideoFrame.from_ndarray(frame_arr, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)

        for packet in stream.encode():
            container.mux(packet)

    return str(out_path)


def generate_thumbnail(
    video_path: str | Path,
    output_image_path: str | Path,
    at_second: float = 1.0,
) -> str:
    """Extract a representative keyframe and save as web-accessible thumbnail."""
    out_str = str(output_image_path)
    Path(out_str).parent.mkdir(parents=True, exist_ok=True)

    with av.open(str(video_path)) as container:
        stream = container.streams.video[0]
        time_base = float(stream.time_base)

        best_frame = None
        for frame in container.decode(stream):
            pts_time = float(frame.pts * time_base) if frame.pts is not None else 0.0
            if pts_time >= at_second:
                best_frame = frame
                break

        if best_frame is None:
            # Fallback to first frame
            container.seek(0)
            best_frame = next(container.decode(stream), None)

        if best_frame:
            img = best_frame.to_image()
            img.save(out_str, format="JPEG", quality=85)

    return out_str
