"""Apply package-specific coverage thresholds to coverage.py JSON output."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    report_path = Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.json")
    if not report_path.is_file():
        print(f"Coverage report not found: {report_path}")
        return 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    overall = float(report.get("totals", {}).get("percent_covered", 0.0))
    required: dict[str, float] = {"surgisight/contract/": 90.0, "surgisight/analytics/": 90.0}
    failures: list[str] = []
    files = report.get("files", {})
    for package, threshold in required.items():
        selected = [
            item.get("summary", {})
            for path, item in files.items()
            if path.replace("\\", "/").startswith(package)
        ]
        statements = sum(int(item.get("num_statements", 0)) for item in selected)
        covered = sum(int(item.get("covered_lines", 0)) for item in selected)
        measured = 100.0 * covered / statements if statements else 0.0
        print(f"{package} coverage={measured:.2f}% required={threshold:.2f}%")
        if not statements or measured < threshold:
            failures.append(f"{package} below {threshold:.2f}%")
    print(f"overall coverage={overall:.2f}% required=80.00%")
    if overall < 80.0:
        failures.append("overall coverage below 80.00%")
    if failures:
        print("Coverage gate failed: " + "; ".join(failures))
        return 1
    print("Coverage gate passed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
