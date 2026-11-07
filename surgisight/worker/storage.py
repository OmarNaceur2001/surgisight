"""Atomic Parquet serialization for frame-level prediction streams."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from surgisight.contract.models import DetectionRecord, PerSecondRecord
from surgisight.contract.types import PHASE_ORDER, TOOL_ORDER
from surgisight.settings import settings


def get_run_storage_dir(run_id: str) -> Path:
    """Return the controlled storage directory for a run."""
    run_dir = Path(settings.storage_dir) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _atomic_parquet_write(table: pa.Table, path: Path) -> None:
    """Write into a sibling temporary file then atomically replace the destination."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, str(tmp_path), compression="snappy")
    os.replace(tmp_path, path)


def save_1hz_predictions_parquet(run_id: str, records: list[PerSecondRecord]) -> str:
    """Persist complete 1 Hz probabilities and structured triplets atomically."""
    run_dir = get_run_storage_dir(run_id)
    final_path = run_dir / "predictions_1hz.parquet"
    data: dict[str, pa.Array] = {
        "t": pa.array([r.t for r in records], type=pa.float64()),
        "frame_idx": pa.array([r.frame_idx if r.frame_idx is not None else -1 for r in records], type=pa.int64()),
        "phase_label": pa.array([r.phase.label.value for r in records], type=pa.string()),
        "phase_conf": pa.array([r.phase.confidence for r in records], type=pa.float64()),
        "triplets_json": pa.array(
            [json.dumps([item.model_dump(mode="json") for item in r.triplets]) for r in records],
            type=pa.string(),
        ),
        "quality_flags": pa.array([list(r.quality_flags) for r in records], type=pa.list_(pa.string())),
    }
    for phase in PHASE_ORDER:
        data[f"phase_prob_{phase.value}"] = pa.array(
            [float(r.phase.probs[phase]) for r in records], type=pa.float64()
        )
    for tool in TOOL_ORDER:
        data[f"tool_{tool.value}"] = pa.array(
            [float(r.tools.probs[tool]) for r in records], type=pa.float64()
        )
    _atomic_parquet_write(pa.Table.from_pydict(data), final_path)
    return str(final_path)


def save_5hz_detections_parquet(run_id: str, records: list[DetectionRecord]) -> str:
    """Persist 5 Hz detection boxes atomically."""
    run_dir = get_run_storage_dir(run_id)
    final_path = run_dir / "predictions_5hz.parquet"
    data = {
        "t": pa.array([r.t for r in records], type=pa.float64()),
        "tool": pa.array([r.tool.value for r in records], type=pa.string()),
        "score": pa.array([r.score for r in records], type=pa.float64()),
        "track_id": pa.array([r.track_id if r.track_id is not None else -1 for r in records], type=pa.int32()),
        "x1": pa.array([r.bbox[0] for r in records], type=pa.float32()),
        "y1": pa.array([r.bbox[1] for r in records], type=pa.float32()),
        "x2": pa.array([r.bbox[2] for r in records], type=pa.float32()),
        "y2": pa.array([r.bbox[3] for r in records], type=pa.float32()),
    }
    _atomic_parquet_write(pa.Table.from_pydict(data), final_path)
    return str(final_path)


def read_predictions_parquet(run_id: str, stream: str = "1hz") -> pa.Table:
    """Read a persisted Parquet prediction stream."""
    if stream not in {"1hz", "5hz"}:
        raise ValueError("stream must be '1hz' or '5hz'")
    run_dir = get_run_storage_dir(run_id)
    filename = "predictions_1hz.parquet" if stream == "1hz" else "predictions_5hz.parquet"
    file_path = run_dir / filename
    if not file_path.exists():
        raise FileNotFoundError(f"Parquet predictions not found: {file_path}")
    return pq.read_table(str(file_path))
