# ADR-0004: Use ReportLab for PDF generation

**Status**: Accepted  
**Date**: 2026-11-06

## Context
PDF generation must work on Windows without GTK (which WeasyPrint requires). ReportLab is a pure-Python PDF library with no C extensions beyond optional accelerators, well-maintained, and widely used.

## Decision
Use `reportlab==4.4.1` as the primary PDF renderer. The renderer is placed behind a `PdfRenderer` interface so WeasyPrint can be substituted on Linux.

## Consequences
- No GTK or OS-level font rendering needed.
- ReportLab's Platypus framework is used for page layout.
- PDF generation target: < 30 seconds for a 90-minute video report.
