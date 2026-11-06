#!/usr/bin/env python3
"""Export Data Contract v1.0 JSON Schemas and color palette.

Usage:
    python scripts/export_schemas.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from surgisight.contract import (  # noqa: E402
    AnalysisRun,
    Correction,
    DetectionRecord,
    PerSecondRecord,
    Report,
    StreamMessage,
    Track,
    VideoMeta,
    get_palette_export,
)

ROOT = Path(__file__).resolve().parent.parent

SCHEMAS: dict[str, type] = {
    "PerSecondRecord.schema.json": PerSecondRecord,
    "DetectionRecord.schema.json": DetectionRecord,
    "Track.schema.json": Track,
    "Report.schema.json": Report,
    "Correction.schema.json": Correction,
    "StreamMessage.schema.json": StreamMessage,
    "VideoMeta.schema.json": VideoMeta,
    "AnalysisRun.schema.json": AnalysisRun,
}


def export() -> None:
    # 1. Export JSON Schemas
    schema_dirs = [
        ROOT / "contract" / "schemas",
        ROOT / "surgisight" / "contract" / "schemas",
    ]
    for d in schema_dirs:
        d.mkdir(parents=True, exist_ok=True)

    for filename, model_cls in SCHEMAS.items():
        schema_dict = model_cls.model_json_schema()
        content = json.dumps(schema_dict, indent=2, sort_keys=True)
        for target_dir in schema_dirs:
            target_path = target_dir / filename
            target_path.write_text(content + "\n", encoding="utf-8")
            print(f"Exported: {target_path.relative_to(ROOT)}")

    # 2. Export Palette to frontend and contract
    palette_data = get_palette_export()
    palette_json = json.dumps(palette_data, indent=2, sort_keys=True) + "\n"

    palette_targets = [
        ROOT / "contract" / "palette.json",
        ROOT / "surgisight" / "contract" / "palette.json",
        ROOT / "web" / "src" / "palette.json",
    ]
    for target in palette_targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(palette_json, encoding="utf-8")
        print(f"Exported palette: {target.relative_to(ROOT)}")


if __name__ == "__main__":
    export()
