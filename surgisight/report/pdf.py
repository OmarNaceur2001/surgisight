"""ReportLab PDF renderer for SurgiSight Operative Reports (M6).

Guarantees:
- Principle P1: Banner 'Research prototype — not for clinical use' on EVERY page.
- Principle P3: Zero forbidden evaluative words (validated via lexicon).
- Principle P4: Every number in the text is grounded in report.json.
- Principle P6: Explicit review status (DRAFT_PENDING_REVIEW / REVIEWED) on every page.
- Fast execution (< 5 seconds).
"""

from __future__ import annotations

import io
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from surgisight.contract.models import Report
from surgisight.contract.types import RESEARCH_DISCLAIMER
from surgisight.report.chart import render_timeline_chart
from surgisight.report.renderer import ReportRenderer


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas that adds running headers, footers, and page numbers on every page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#C0392B"))  # Alert Crimson

        # Header: Research notice banner (P1)
        self.drawString(
            36,
            756,
            "Research prototype — not for clinical use",
        )

        # Header: Review Status (P6)
        status_text = getattr(self, "report_status_text", "DRAFT_PENDING_REVIEW")
        status_color = (
            colors.HexColor("#27AE60")
            if "REVIEWED" in status_text and "PENDING" not in status_text
            else colors.HexColor("#D35400")
        )
        self.setFillColor(status_color)
        self.drawRightString(576, 756, f"Status: {status_text}")

        # Top divider line
        self.setStrokeColor(colors.HexColor("#BDC3C7"))
        self.setLineWidth(0.5)
        self.line(36, 750, 576, 750)

        # Bottom divider line
        self.line(36, 42, 576, 42)

        # Footer: Research notice + Page numbering
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#7F8C8D"))
        self.drawString(
            36,
            30,
            "Research prototype — not for clinical use | SurgiSight v1.0",
        )
        self.drawRightString(576, 30, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


class ReportLabPdfRenderer(ReportRenderer):
    """Production ReportLab PDF generator."""

    def render_pdf(self, report: Report, output_path: str | Path | None = None) -> bytes:
        """Render report into PDF binary bytes."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=36,
            rightMargin=36,
            topMargin=54,
            bottomMargin=54,
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#2C3E50"),
            spaceAfter=6,
        )

        h2_style = ParagraphStyle(
            "DocH2",
            parent=styles["Heading2"],
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#2C3E50"),
            spaceBefore=10,
            spaceAfter=4,
        )

        body_style = ParagraphStyle(
            "DocBody",
            parent=styles["Normal"],
            fontSize=8.5,
            leading=11.5,
            textColor=colors.HexColor("#34495E"),
        )

        disclaimer_style = ParagraphStyle(
            "DocDisclaimer",
            parent=styles["Normal"],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#78281F"),
        )

        story = []

        # Title
        story.append(Paragraph("SurgiSight Surgical Operative Report", title_style))
        story.append(
            HRFlowable(width="100%", thickness=1, color=colors.HexColor("#34495E"), spaceAfter=8)
        )

        # Metadata Block
        meta_data = [
            [
                Paragraph(f"<b>Video ID:</b> {report.video_id}", body_style),
                Paragraph(f"<b>Dataset:</b> {report.dataset}", body_style),
            ],
            [
                Paragraph(
                    f"<b>Duration:</b> {report.duration_s:.1f}s",
                    body_style,
                ),
                Paragraph(f"<b>Review Status:</b> {report.status.value}", body_style),
            ],
            [
                Paragraph(
                    f"<b>Producer:</b> {report.producer.name} v{report.producer.version}",
                    body_style,
                ),
                Paragraph(f"<b>Schema:</b> v{report.schema_version}", body_style),
            ],
        ]
        meta_table = Table(meta_data, colWidths=[270, 270])
        meta_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8F9F9")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D5D8DC")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(meta_table)
        story.append(Spacer(1, 8))

        # Mandatory Research Disclaimer Box (P1)
        disc_table = Table(
            [
                [
                    Paragraph(
                        f"<b>RESEARCH NOTICE (NON-CLINICAL USE):</b> {RESEARCH_DISCLAIMER}",
                        disclaimer_style,
                    )
                ]
            ],
            colWidths=[540],
        )
        disc_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FDEDEC")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#E74C3C")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(disc_table)
        story.append(Spacer(1, 10))

        # Phase Timeline Section
        story.append(Paragraph("1. Surgical Phase Timeline", h2_style))
        chart_buf = render_timeline_chart(
            report.phases, report.duration_s, width_in=7.2, height_in=1.2
        )
        story.append(Image(chart_buf, width=7.2 * inch, height=1.2 * inch))
        story.append(Spacer(1, 6))

        # Phase breakdown table
        phase_rows = [
            ["Phase", "Name", "Start (s)", "End (s)", "Duration (s)", "Confidence", "Status"]
        ]
        for p in report.phases:
            status_flag = "Uncertain" if p.uncertain else "Standard"
            phase_rows.append(
                [
                    p.label.value,
                    p.name,
                    f"{p.start:.1f}",
                    f"{p.end:.1f}",
                    f"{p.duration_s:.1f}",
                    f"{p.conf:.2f}",
                    status_flag,
                ]
            )
        phase_table = Table(phase_rows, colWidths=[40, 170, 60, 60, 70, 70, 70])
        phase_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("ALIGN", (2, 0), (5, -1), "RIGHT"),
                    ("ALIGN", (0, 0), (1, -1), "LEFT"),
                    ("ALIGN", (6, 0), (6, -1), "CENTER"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ]
            )
        )
        story.append(phase_table)
        story.append(Spacer(1, 10))

        # Tool Usage Breakdown
        story.append(Paragraph("2. Instrument Usage Summary", h2_style))
        tool_rows = [["Instrument", "Active Duration (s)", "Procedure Usage %"]]
        for tu in report.tools:
            tool_rows.append([tu.tool.value, f"{tu.usage_s:.1f}", f"{tu.pct:.1f}%"])
        tool_table = Table(tool_rows, colWidths=[200, 170, 170])
        tool_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495E")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ]
            )
        )
        story.append(tool_table)
        story.append(Spacer(1, 10))

        # Key Surgical Milestones
        if report.events:
            story.append(Paragraph("3. Key Surgical Milestones", h2_style))
            ev_rows = [["Milestone", "Timestamp (s)", "Confidence", "Certainty", "Evidence"]]
            for ev in report.events:
                cert = "Flagged Uncertain" if ev.uncertain else "Standard"
                ev_desc = "; ".join(ev.evidence) if ev.evidence else "-"
                ev_rows.append(
                    [
                        ev.type,
                        f"{ev.t:.1f}",
                        f"{ev.conf:.2f}",
                        cert,
                        Paragraph(ev_desc, body_style),
                    ]
                )
            ev_table = Table(ev_rows, colWidths=[120, 65, 55, 75, 225])
            ev_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495E")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                        ("ALIGN", (1, 0), (2, -1), "RIGHT"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(ev_table)
            story.append(Spacer(1, 10))

        # Cohort Deviations (P3 neutral wording)
        if report.deviations:
            story.append(Paragraph("4. Reference Cohort Duration Comparisons", h2_style))
            dev_rows = [
                ["Phase", "Observed Duration (s)", "Cohort p95 (s)", "Cohort Size", "Observation"]
            ]
            for d in report.deviations:
                dev_rows.append(
                    [
                        d.phase.value,
                        f"{d.value_s:.1f}",
                        f"{d.cohort_p95_s:.1f}" if d.cohort_p95_s is not None else "-",
                        str(d.cohort_n),
                        Paragraph(d.wording, body_style),
                    ]
                )
            dev_table = Table(dev_rows, colWidths=[50, 95, 75, 60, 260])
            dev_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7F8C8D")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                        ("ALIGN", (1, 0), (3, -1), "RIGHT"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(dev_table)
            story.append(Spacer(1, 10))

        # Model Provenance & Confidence Notes
        prov_story = [
            Paragraph("5. Model Provenance and Quality Notes", h2_style),
        ]
        model_rows = [["Pipeline Component", "Version / Artifact Hash"]]
        for comp, ver in report.models.items():
            model_rows.append([comp, ver])
        model_table = Table(model_rows, colWidths=[200, 340])
        model_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7F8C8D")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ]
            )
        )
        prov_story.append(model_table)

        if report.confidence_notes:
            prov_story.append(Spacer(1, 4))
            for note in report.confidence_notes:
                prov_story.append(Paragraph(f"• {note}", body_style))

        story.append(KeepTogether(prov_story))

        # Configure canvas status
        def canvas_maker(*args, **kwargs):
            c = NumberedCanvas(*args, **kwargs)
            c.report_status_text = report.status.value
            return c

        doc.build(story, canvasmaker=canvas_maker)
        pdf_bytes = buffer.getvalue()

        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "wb") as f:
                f.write(pdf_bytes)

        return pdf_bytes
