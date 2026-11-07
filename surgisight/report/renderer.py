"""Report renderer protocol interface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from surgisight.contract.models import Report


@runtime_checkable
class ReportRenderer(Protocol):
    """Protocol for rendering a verified Report into export formats."""

    def render_pdf(self, report: Report, output_path: str | Path | None = None) -> bytes:
        """Render report into PDF binary bytes."""
        ...
