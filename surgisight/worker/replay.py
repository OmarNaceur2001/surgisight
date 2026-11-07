"""Validated read-only reconstruction of 1 Hz contract records from local Parquet."""
from __future__ import annotations

import json
from collections.abc import Iterator

from surgisight.contract.models import (
    PerSecondRecord, PhasePrediction, ProducerInfo, ToolPresencePrediction, TripletPrediction
)
from surgisight.contract.types import PHASE_ORDER, TOOL_ORDER, PhaseId
from surgisight.worker.storage import read_predictions_parquet


def iter_per_second_records(run_id: str) -> Iterator[PerSecondRecord]:
    """Yield contract-validated records from locally stored predictions."""
    table = read_predictions_parquet(run_id, stream="1hz")
    for row in table.to_pylist():
        label = PhaseId(row["phase_label"])
        probabilities = {
            phase: float(row.get(f"phase_prob_{phase.value}", 0.0))
            for phase in PHASE_ORDER
        }
        if sum(probabilities.values()) <= 0:
            confidence = float(row.get("phase_conf", 1.0))
            residual = max(0.0, 1.0 - confidence) / (len(PHASE_ORDER) - 1)
            probabilities = {
                phase: confidence if phase == label else residual for phase in PHASE_ORDER
            }
        tools = {tool: float(row.get(f"tool_{tool.value}", 0.0)) for tool in TOOL_ORDER}
        raw_triplets = json.loads(row.get("triplets_json") or "[]")
        frame_idx = int(row.get("frame_idx", -1))
        yield PerSecondRecord(
            producer=ProducerInfo(name="surgisight.worker.replay", version="1.0"),
            t=float(row["t"]),
            frame_idx=frame_idx if frame_idx >= 0 else None,
            phase=PhasePrediction(label=label, probs=probabilities),
            tools=ToolPresencePrediction(probs=tools),
            triplets=[TripletPrediction.model_validate(item) for item in raw_triplets],
            quality_flags=row.get("quality_flags") or [],
        )
