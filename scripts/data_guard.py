#!/usr/bin/env python3
"""Pre-commit hook: reject files matching media/weight/archive patterns or > 5 MB.

Usage (called by pre-commit):
    python scripts/data_guard.py [filenames...]
"""

from __future__ import annotations

import os
import sys

# Patterns that must never be committed anywhere in the repository (P2 -- licence compliance)
ALWAYS_FORBIDDEN_EXTENSIONS = {
    # Video containers
    ".mp4",
    ".avi",
    ".mkv",
    ".mov",
    ".webm",
    ".flv",
    ".wmv",
    # Archives
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".rar",
    ".7z",
    # Model weights & large binary arrays
    ".pt",
    ".pth",
    ".bin",
    ".npy",
    ".npz",
    ".h5",
    ".hdf5",
    ".pkl",
    ".onnx",
}

# Image extensions (disallowed in data/code folders to prevent raw dataset frame leakage)
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
}

# Folders allowed to contain small UI/documentation images
ALLOWED_IMAGE_PREFIXES = (
    "web" + os.sep,
    "web/",
    "docs" + os.sep,
    "docs/",
)

SIZE_LIMIT_BYTES = 5 * 1024 * 1024  # 5 MB


def check(filenames: list[str]) -> int:
    """Return 1 (fail) if any filename violates the guard rules, else 0."""
    failures: list[str] = []
    for path in filenames:
        norm_path = os.path.normpath(path)
        ext = os.path.splitext(norm_path)[1].lower()

        # 1. Always forbidden extensions (videos, archives, weights)
        if ext in ALWAYS_FORBIDDEN_EXTENSIONS:
            failures.append(f"  FORBIDDEN EXTENSION: {path}  (ext={ext})")
            continue

        # 2. Frame / dataset path check
        parts = norm_path.lower().split(os.sep)
        if any(
            p.startswith("frame") or p.startswith("embedding") or p == "data_raw" for p in parts
        ):
            failures.append(f"  FORBIDDEN PATH PATTERN: {path} (dataset/frame folder)")
            continue

        # 3. Image files outside web/ or docs/ (reject raw frames dumped in code/root)
        if ext in IMAGE_EXTENSIONS:
            is_allowed = any(
                norm_path.startswith(prefix)
                for prefix in ("web" + os.sep, "docs" + os.sep, "web/", "docs/")
            )
            if not is_allowed:
                failures.append(
                    f"  RAW FRAME / IMAGE OUTSIDE WEB OR DOCS: {path} (only UI assets in web/ or docs/ permitted)"
                )
                continue

        # 4. File size limit (< 5 MB)
        if os.path.isfile(path):
            size = os.path.getsize(path)
            if size > SIZE_LIMIT_BYTES:
                failures.append(
                    f"  FILE TOO LARGE: {path}  ({size / 1_048_576:.1f} MB > 5 MB limit)"
                )

    if failures:
        print("data-guard: Commit rejected -- the following files are not allowed:")
        print("\n".join(failures))
        print("\nHint: add to .gitignore or remove from staging area.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(check(sys.argv[1:]))
