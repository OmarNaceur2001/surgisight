"""Atomic report.json and PDF export from the validated JSON source of truth."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TypedDict

from surgisight.analytics.lexicon import validate_object_lexicon
from surgisight.contract.models import Report
from surgisight.report.pdf import ReportLabPdfRenderer
from surgisight.report.renderer import ReportRenderer


class ReportExportPaths(TypedDict):
    """Paths written by :func:`export_report`."""

    report_json: Path
    report_pdf: Path


def _atomic_write(path: Path, content: bytes) -> None:
    """Write bytes to a sibling temporary file, then atomically replace the destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def export_report(
    report: Report,
    output_dir: str | Path,
    renderer: ReportRenderer | None = None,
) -> ReportExportPaths:
    """Persist report.json and render the PDF from the reloaded JSON document.

    The JSON file is the canonical report source. The supplied in-memory object is
    serialized, validated again from those exact bytes, and only then passed to the
    renderer. Both outputs are replaced atomically to avoid partial files.
    """
    destination = Path(output_dir)
    json_path = destination / "report.json"
    pdf_path = destination / "report.pdf"

    payload = report.model_dump_json(indent=2).encode("utf-8")
    parsed_payload = json.loads(payload)
    validate_object_lexicon(parsed_payload, path="report.json")
    canonical_report = Report.model_validate_json(payload)

    active_renderer = renderer or ReportLabPdfRenderer()
    pdf_bytes = active_renderer.render_pdf(canonical_report)
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("Report renderer did not return a PDF document.")

    # Write the canonical JSON first. The PDF has been generated from that same JSON.
    _atomic_write(json_path, payload + b"\n")
    _atomic_write(pdf_path, pdf_bytes)

    return {"report_json": json_path, "report_pdf": pdf_path}
