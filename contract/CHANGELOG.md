# SurgiSight Data Contract Changelog

All notable changes to the SurgiSight Data Contract will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-11-06 (FROZEN)

Initial freeze of the SurgiSight Data Contract v1.0. Any modification to existing schemas
requires a version increment and updating the committed JSON schemas.

### Added
- **Primary Time Representation**:
  - `t` (float, rounded to 2 decimal places, representing elapsed seconds from start) is the primary key.
  - `frame_idx` (integer, based on canonical 25 FPS) is optional.
- **Interval and Tiling Conventions**:
  - Half-open intervals `[start, end)` in seconds.
  - Full tiling requirement: `PhaseSegment` sequences must tile `[0.0, duration_s)` with no gaps and no overlaps.
- **Streams**:
  - `PerSecondRecord` (1 Hz): Synchronized phase predictions, 7-tool presence probabilities, top action triplets, optical quality flags.
  - `DetectionRecord` (5 Hz): Spatial bounding boxes `[x1, y1, x2, y2]` in cropped-frame px, tool class, confidence, track ID.
  - `Track`: Multi-interval spatiotemporal trajectory for instrument tracking.
- **Enumerations**:
  - Phases P1..P7:
    - P1: Preparation
    - P2: Calot triangle dissection
    - P3: Clipping and cutting
    - P4: Gallbladder dissection
    - P5: Gallbladder packaging
    - P6: Cleaning and coagulation
    - P7: Gallbladder retraction
  - Tools (7): `Grasper`, `Bipolar`, `Hook`, `Scissors`, `Clipper`, `Irrigator`, `SpecimenBag`.
- **Confidence & Uncertainty (P5)**:
  - Minimum confidence over segment/event evidence frames.
  - Flagged `uncertain=True` when confidence is below calibrated threshold (default 0.50).
- **Operative Report (P4)**:
  - `Report` model acts as single source of truth for PDF generation.
  - Grounded traceability: all numbers in report must map to JSON fields.
- **Color Palette**:
  - Standardized accessible, color-blind safe palette defined in `surgisight.contract.palette` and exported to `contract/palette.json` and `web/src/palette.json`.
- **JSON Schemas**:
  - Exported schemas in `contract/schemas/*.json` for `PerSecondRecord`, `DetectionRecord`, `Track`, `Report`, `Correction`, `StreamMessage`, `VideoMeta`, `AnalysisRun`.
- **Deterministic Mock Generator**:
  - `generate_mock_analysis(duration_minutes, seed)` generating realistic, fully validated cholecystectomy procedures.
