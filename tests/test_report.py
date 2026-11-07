"""Tests for Report Generator (M6), Traceability (P4), and Lexicon (P3)."""

from __future__ import annotations

import io
import re
import time

import pypdf
import pytest

from surgisight.analytics.lexicon import find_forbidden_words
from surgisight.contract.mock_generator import generate_mock_analysis
from surgisight.contract.models import Report
from surgisight.contract.types import ReportStatus
from surgisight.report.builder import build_report
from surgisight.report.pdf import ReportLabPdfRenderer


@pytest.fixture
def mock_report() -> Report:
    """Deterministic mock report for testing."""
    res = generate_mock_analysis(duration_minutes=25.0, seed=42)
    return res.report


class TestReportGenerator:
    def test_build_report_validation(self, mock_report: Report):
        """Report builder validates tiling and lexicon cleanly."""
        rebuilt = build_report(
            video_id=mock_report.video_id,
            dataset=mock_report.dataset,
            duration_s=mock_report.duration_s,
            phases=mock_report.phases,
            tools=mock_report.tools,
            events=mock_report.events,
            deviations=mock_report.deviations,
            triplet_highlights=mock_report.triplet_highlights,
            models=mock_report.models,
            confidence_notes=mock_report.confidence_notes,
            status=ReportStatus.DRAFT_PENDING_REVIEW,
        )
        assert rebuilt.duration_s == mock_report.duration_s
        assert rebuilt.status == ReportStatus.DRAFT_PENDING_REVIEW

    def test_pdf_rendering_performance(self, mock_report: Report):
        """PDF rendering must execute well under the 30-second requirement (< 5s)."""
        renderer = ReportLabPdfRenderer()
        t0 = time.perf_counter()
        pdf_bytes = renderer.render_pdf(mock_report)
        elapsed = time.perf_counter() - t0

        assert len(pdf_bytes) > 1000
        assert elapsed < 5.0, f"PDF generation took {elapsed:.2f}s, expected < 5s"

    def test_disclaimer_and_status_on_every_page(self, mock_report: Report):
        """Principle P1 & P6: Research disclaimer and review status banner on EVERY page."""
        renderer = ReportLabPdfRenderer()
        pdf_bytes = renderer.render_pdf(mock_report)

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        num_pages = len(reader.pages)
        assert num_pages >= 1

        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            # Non-negotiable P1: Banner on every page
            assert (
                "Research prototype" in text and "not for clinical use" in text
            ), f"Research disclaimer missing from page {i + 1}"
            # Non-negotiable P6: Review status on every page
            assert (
                "Status: DRAFT_PENDING_REVIEW" in text or "DRAFT_PENDING_REVIEW" in text
            ), f"Review status missing from page {i + 1}"

    def test_lexicon_clean_pdf(self, mock_report: Report):
        """Principle P3: Zero forbidden evaluative words in PDF content."""
        renderer = ReportLabPdfRenderer()
        pdf_bytes = renderer.render_pdf(mock_report)

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            forbidden = find_forbidden_words(text)
            assert not forbidden, f"Forbidden word(s) {forbidden} found on page {i + 1}"

    def test_traceability_numbers_in_json(self, mock_report: Report):
        """Principle P4: Grounded reporting - numbers in the PDF must trace back to report.json."""
        renderer = ReportLabPdfRenderer()
        pdf_bytes = renderer.render_pdf(mock_report)

        # Collect all numbers appearing in report data
        report_data = mock_report.model_dump()

        def extract_numbers(obj) -> set[str]:
            nums: set[str] = set()
            if isinstance(obj, (int, float)):
                nums.add(f"{obj:.1f}")
                nums.add(f"{obj:.2f}")
                nums.add(f"{obj:.4f}")
                nums.add(str(int(obj)))
                nums.add(str(obj))
            elif isinstance(obj, str):
                for match in re.findall(r"\d+(?:\.\d+)?", obj):
                    nums.add(match)
                    try:
                        val = float(match)
                        nums.add(f"{val:.1f}")
                        nums.add(f"{val:.2f}")
                    except ValueError:
                        pass
            elif isinstance(obj, dict):
                for v in obj.values():
                    nums.update(extract_numbers(v))
            elif isinstance(obj, list):
                for item in obj:
                    nums.update(extract_numbers(item))
            return nums

        grounded_numbers = extract_numbers(report_data)

        # Include phase segment duration properties
        for p in mock_report.phases:
            grounded_numbers.add(f"{p.duration_s:.1f}")
            grounded_numbers.add(f"{p.duration_s:.2f}")

        # Allowable document structural numbers (page numbering, schema version 1.0, sections 1..5)
        layout_numbers = {"1", "2", "3", "4", "5", "1.0", "1.00", "0", "0.0", "0.00"}

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        num_pages = len(reader.pages)
        for p in range(1, num_pages + 1):
            layout_numbers.add(str(p))

        # Extract floats and percentages from PDF text
        all_pdf_text = " ".join(page.extract_text() for page in reader.pages)
        # Matches numbers like 120.0, 45, 95.5%, etc.
        found_tokens = re.findall(r"\b\d+(?:\.\d+)?%?\b", all_pdf_text)

        unmatched = []
        for token in found_tokens:
            cleaned = token.rstrip("%")
            # If token is layout number, skip
            if cleaned in layout_numbers or token in layout_numbers:
                continue
            # Check against grounded report numbers
            is_grounded = (
                cleaned in grounded_numbers
                or token in grounded_numbers
                or any(cleaned in g for g in grounded_numbers)
                or any(
                    float(cleaned) == pytest.approx(float(g), abs=0.1)
                    for g in grounded_numbers
                    if g.replace(".", "", 1).isdigit()
                )
            )
            if not is_grounded:
                unmatched.append(token)

        # Any unmatched numbers must be empty
        assert not unmatched, f"Numbers in PDF not traceable to report.json: {set(unmatched)}"
