"""Single canonical frame preprocessing and black border detection pipeline.

This function is the single pre-processing path shared by training notebooks
and inference serving to prevent training/serving skew (P8).
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# Standard ImageNet normalization parameters (used across laparoscopic vision models)
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def detect_black_borders(
    frame_rgb: np.ndarray,
    luminance_threshold: float = 18.0,
    min_content_ratio: float = 0.50,
) -> list[int]:
    """Detect black circular/rectangular mask borders from endoscopic videos.

    Args:
        frame_rgb: uint8 array (H, W, 3).
        luminance_threshold: pixel brightness below which a pixel is considered black.
        min_content_ratio: minimum valid content dimension as ratio of original size.

    Returns:
        [x, y, cropped_width, cropped_height]
    """
    height, width = frame_rgb.shape[:2]
    # Calculate grayscale brightness: 0.299 R + 0.587 G + 0.114 B
    gray = 0.299 * frame_rgb[:, :, 0] + 0.587 * frame_rgb[:, :, 1] + 0.114 * frame_rgb[:, :, 2]

    # Threshold binary mask where content is present
    content_mask = gray > luminance_threshold

    # Find row and column projections
    row_sums = content_mask.sum(axis=1)
    col_sums = content_mask.sum(axis=0)

    # Minimum number of bright pixels to consider a row/column part of the image
    min_row_px = width * 0.05
    min_col_px = height * 0.05

    valid_rows = np.where(row_sums > min_row_px)[0]
    valid_cols = np.where(col_sums > min_col_px)[0]

    if len(valid_rows) == 0 or len(valid_cols) == 0:
        # Fallback to entire frame if no distinct content found
        return [0, 0, width, height]

    y_min, y_max = int(valid_rows[0]), int(valid_rows[-1])
    x_min, x_max = int(valid_cols[0]), int(valid_cols[-1])

    cropped_w = max(1, x_max - x_min + 1)
    cropped_h = max(1, y_max - y_min + 1)

    # Safety bounds check
    if cropped_w < width * min_content_ratio or cropped_h < height * min_content_ratio:
        return [0, 0, width, height]

    return [x_min, y_min, cropped_w, cropped_h]


def apply_crop(frame_rgb: np.ndarray, crop_offset: list[int] | None) -> np.ndarray:
    """Crop image according to [x, y, w, h] offset."""
    if not crop_offset or len(crop_offset) != 4:
        return frame_rgb
    x, y, w, h = crop_offset
    H, W = frame_rgb.shape[:2]
    x1 = max(0, min(W - 1, x))
    y1 = max(0, min(H - 1, y))
    x2 = max(x1 + 1, min(W, x1 + w))
    y2 = max(y1 + 1, min(H, y1 + h))
    return frame_rgb[y1:y2, x1:x2]


def frame_transform(
    frame_rgb_uint8: np.ndarray,
    crop_offset: list[int] | None = None,
    target_size: tuple[int, int] = (224, 224),
    normalize: bool = True,
) -> np.ndarray:
    """Single canonical frame transformation for training and serving.

    Pipeline:
    1. Apply black-border crop if crop_offset provided.
    2. Resize to target_size (default 224x224) using bilinear interpolation.
    3. Scale to [0.0, 1.0].
    4. Normalize with ImageNet mean and standard deviation.
    5. Return float32 array in channels-first format (3, H, W).

    Args:
        frame_rgb_uint8: Input frame as uint8 array (H, W, 3).
        crop_offset: Optional [x, y, w, h] crop coordinates.
        target_size: (width, height) output dimensions.
        normalize: Whether to apply ImageNet mean/std normalization.

    Returns:
        Processed array of shape (3, target_height, target_width), dtype float32.
    """
    if frame_rgb_uint8.dtype != np.uint8:
        frame_rgb_uint8 = frame_rgb_uint8.astype(np.uint8)

    # 1. Crop
    cropped = apply_crop(frame_rgb_uint8, crop_offset)

    # 2. Resize with Pillow (PIL.Image.BILINEAR)
    img = Image.fromarray(cropped)
    resized_img = img.resize(target_size, resample=Image.Resampling.BILINEAR)
    arr = np.asarray(resized_img, dtype=np.float32) / 255.0

    # 3. Normalize
    if normalize:
        arr = (arr - IMAGENET_MEAN) / IMAGENET_STD

    # 4. Transpose from (H, W, C) to (C, H, W)
    chw = np.transpose(arr, (2, 0, 1))
    return np.ascontiguousarray(chw, dtype=np.float32)
