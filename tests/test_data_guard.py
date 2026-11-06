"""Tests for the data-guard pre-commit hook."""

from __future__ import annotations

import os
from pathlib import Path


def _run_guard(files: list[str]) -> int:
    import sys

    sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), "..", "scripts")))
    from data_guard import check

    return check(files)


def test_guard_allows_python_file(tmp_path: Path) -> None:
    f = tmp_path / "model.py"
    f.write_text("x = 1")
    assert _run_guard([str(f)]) == 0


def test_guard_rejects_mp4() -> None:
    assert _run_guard(["video.mp4"]) == 1


def test_guard_rejects_pt() -> None:
    assert _run_guard(["weights.pt"]) == 1


def test_guard_rejects_zip() -> None:
    assert _run_guard(["dataset.zip"]) == 1


def test_guard_rejects_large_file(tmp_path: Path) -> None:
    f = tmp_path / "big.bin"
    # Write 6 MB
    f.write_bytes(b"x" * (6 * 1024 * 1024))
    assert _run_guard([str(f)]) == 1


def test_guard_allows_small_file(tmp_path: Path) -> None:
    f = tmp_path / "small.csv"
    f.write_text("a,b,c\n1,2,3")
    assert _run_guard([str(f)]) == 0


def test_guard_rejects_frame_outside_web() -> None:
    assert _run_guard(["frames/frame_001.jpg"]) == 1
    assert _run_guard(["data/frame_001.png"]) == 1


def test_guard_allows_web_asset() -> None:
    assert _run_guard(["web/src/assets/hero.png"]) == 0
