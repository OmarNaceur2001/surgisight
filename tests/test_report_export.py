"""Tests for canonical JSON-to-PDF report export (WP8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from surgisight.contract.mock_generator import generate_mock_analysis

from surgisight.contract.models import Report
from surgisight.report.export import export_report


@pytest.fixture
def mock_report() -> Report:
    """Generate a deterministic mock report; no dataset files are used."""
    return generate_mock_analysis(duration_minutes=25.0, seed=42).report


class CapturingRenderer:
    """Small renderer fixture that records the exact parsed report it receives."""

    def __init__(self) -> None:
        self.report: Report | None = None

    def render_pdf(self, report: Report, output_path: str | Path | None = None) -> bytes:
        self.report = report
        return b"%PDF-1.4\nsynthetic fixture only\n%%EOF"


def test_export_renders_from_canonical_report_json(mock_report: Report, tmp_path: Path) -> None:
    """Renderer receives the model re-created from the exact persisted JSON payload."""
    renderer = CapturingRenderer()

    result = export_report(mock_report, tmp_path, renderer=renderer)

    assert result["report_json"].is_file()
    assert result["report_pdf"].is_file()
    assert result["report_pdf"].read_bytes().startswith(b"%PDF-")
    exported_data = json.loads(result["report_json"].read_text(encoding="utf-8"))
    assert exported_data["video_id"] == str(mock_report.video_id)
    assert exported_data["disclaimer"] == mock_report.disclaimer
    assert renderer.report is not None
    assert renderer.report.model_dump(mode="json") == Report.model_validate(exported_data).model_dump(mode="json")


def test_export_rejects_non_pdf_renderer_output(mock_report: Report, tmp_path: Path) -> None:
    """A renderer response without a PDF signature is not accepted."""
    class InvalidRenderer:
        def render_pdf(self, report: Report, output_path: str | Path | None = None) -> bytes:
            return b"not-a-pdf"

    try:
        export_report(mock_report, tmp_path, renderer=InvalidRenderer())
    except ValueError as exc:
        assert "PDF document" in str(exc)
    else:
        raise AssertionError("Expected invalid renderer output to be rejected.")
