"""SurgiSight Worker package.

Provides:
- Database-backed queue claiming and idempotency
- Pipeline stage orchestrator
- Parquet storage for 1 Hz and 5 Hz records
"""

from __future__ import annotations

from surgisight.worker.orchestrator import PipelineOrchestrator, StageExecutionError
from surgisight.worker.queue import claim_next_run, enqueue_analysis_run
from surgisight.worker.storage import (
    read_predictions_parquet,
    save_1hz_predictions_parquet,
    save_5hz_detections_parquet,
)

__all__ = [
    "PipelineOrchestrator",
    "StageExecutionError",
    "claim_next_run",
    "enqueue_analysis_run",
    "read_predictions_parquet",
    "save_1hz_predictions_parquet",
    "save_5hz_detections_parquet",
]
