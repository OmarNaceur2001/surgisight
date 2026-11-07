"""SurgiSight Report Generation Module (M6).

Provides:
- Data Contract v1.0 Report builder
- ReportLab Platypus PDF renderer
- Traceability, Lexicon, and Grounded Reporting checks
"""

from surgisight.report.builder import build_report
from surgisight.report.chart import render_timeline_chart
from surgisight.report.pdf import ReportLabPdfRenderer
from surgisight.report.renderer import ReportRenderer

__all__ = [
    "ReportLabPdfRenderer",
    "ReportRenderer",
    "build_report",
    "render_timeline_chart",
]
