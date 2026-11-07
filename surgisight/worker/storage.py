"""Parquet serialization for frame-level analysis records (WP5).

Frame-level streams stay in Parquet files referenced by analysis_runs,
never stored directly as high-volume database rows.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from surgisight.contract.models import DetectionRecord, PerSecondRecord
from surgisight.settings import settings


def get_run_storage_dir(run_id: str) -> Path:
    """Return directory path for run artifacts."""
    run_dir = Path(settings.storage_dir) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def save_1hz_predictions_parquet(run_id: str, records: list[PerSecondRecord]) -> str:
    """Atomically serialize 1 Hz PerSecondRecords to Parquet."""
    run_dir = get_run_storage_dir(run_id)
    final_path = run_dir / "predictions_1hz.parquet"
    tmp_path = run_dir / "predictions_1hz.parquet.tmp"

    # Prepare tabular data
    t_list = [r.t for r in records]
    frame_idx_list = [r.frame_idx if r.frame_idx is not None else -1 for r in records]
    phase_label_list = [r.phase.label.value for r in records]
    phase_conf_list = [r.phase.confidence for r in records]

    # Convert tool probabilities to parallel arrays
    tool_keys = sorted(records[0].tools.probs.keys()) if records else []
    tool_data: dict[str, list[float]] = {
        f"tool_{t.value}": [r.tools.probs.get(t, 0.0) for r in records] for t in tool_keys
    }

    triplet_counts = [len(r.triplets) for r in records]

    data = {
        "t": pa.array(t_list, type=pa.float64()),
        "frame_idx": pa.array(frame_idx_list, type=pa.int64()),
        "phase_label": pa.array(phase_label_list, type=pa.string()),
        "phase_conf": pa.array(phase_conf_list, type=pa.float64()),
        "triplet_count": pa.array(triplet_counts, type=pa.int32()),
    }
    for col, values in tool_data.items():
        data[col] = pa.array(values, type=pa.float64())

    table = pa.Table.from_pydict(data)
    pq.write_table(table, str(tmp_path), compression="snappy")

    # Atomic rename
    os.replace(tmp_path, final_path)
    return str(final_path)


def save_5hz_detections_parquet(run_id: str, records: list[DetectionRecord]) -> str:
    """Atomically serialize 5 Hz DetectionRecords to Parquet."""
    run_dir = get_run_storage_dir(run_id)
    final_path = run_dir / "predictions_5hz.parquet"
    tmp_path = run_dir / "predictions_5hz.parquet.tmp"

    data = {
        "t": pa.array([r.t for r in records], type=pa.float64()),
        "tool": pa.array([r.tool.value for r in records], type=pa.string()),
        "score": pa.array([r.score for r in records], type=pa.float64()),
        "track_id": pa.array(
            [r.track_id if r.track_id is not None else -1 for r in records], type=pa.int32()
        ),
        "x1": pa.array([r.bbox[0] for r in records], type=pa.float32()),
        "y1": pa.array([r.bbox[1] for r in records], type=pa.float32()),
        "x2": pa.array([r.bbox[2] for r in records], type=pa.float32()),
        "y2": pa.array([r.bbox[3] for r in records], type=pa.float32()),
    }

    table = pa.Table.from_pydict(data)
    pq.write_table(table, str(tmp_path), compression="snappy")

    # Atomic rename
    os.replace(tmp_path, final_path)
    return str(final_path)


def read_predictions_parquet(run_id: str, stream: str = "1hz") -> pa.Table:
    """Read serialized predictions Parquet file."""
    run_dir = get_run_storage_dir(run_id)
    filename = "predictions_1hz.parquet" if stream == "1hz" else "predictions_5hz.parquet"
    file_path = run_dir / filename
    if not file_path.exists():
        raise FileNotFoundError(f"Parquet predictions not found: {file_path}")
    return pq.read_table(str(file_path))
