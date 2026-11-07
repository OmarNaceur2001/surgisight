"""SurgiSight Data processing subpackage.

Provides:
- Transforms: detect_black_borders, frame_transform
- Video: probe_video, extract_frames, transcode_and_normalize, generate_synthetic_video, generate_thumbnail
"""

from __future__ import annotations

from surgisight.data.transforms import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    apply_crop,
    detect_black_borders,
    frame_transform,
)
from surgisight.data.video import (
    ALLOWED_CODECS,
    ALLOWED_CONTAINERS,
    VideoValidationError,
    extract_frames,
    generate_synthetic_video,
    generate_thumbnail,
    probe_video,
    transcode_and_normalize,
)

__all__ = [
    "ALLOWED_CODECS",
    "ALLOWED_CONTAINERS",
    "IMAGENET_MEAN",
    "IMAGENET_STD",
    "VideoValidationError",
    "apply_crop",
    "detect_black_borders",
    "extract_frames",
    "frame_transform",
    "generate_synthetic_video",
    "generate_thumbnail",
    "probe_video",
    "transcode_and_normalize",
]
