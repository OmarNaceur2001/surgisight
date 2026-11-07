"""In-process, bounded latency samples for observability (metrics only)."""
from __future__ import annotations

from collections import defaultdict, deque
from math import ceil
from threading import Lock


class LatencyRegistry:
    """Keep a bounded sample window and return p50/p95 summaries per stage."""

    def __init__(self, max_samples: int = 10000) -> None:
        if max_samples < 1:
            raise ValueError("max_samples must be >= 1")
        self._max_samples = max_samples
        self._samples: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self._max_samples)
        )
        self._lock = Lock()

    def record(self, stage: str, latency_ms: float) -> None:
        """Record a non-negative duration in milliseconds."""
        if not stage.strip():
            raise ValueError("stage must be non-empty")
        if latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        with self._lock:
            self._samples[stage].append(float(latency_ms))

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        """Return bounded p50/p95/count metrics; no video or user identifiers are retained."""
        with self._lock:
            copied = {stage: sorted(values) for stage, values in self._samples.items()}
        result: dict[str, dict[str, float | int]] = {}
        for stage, values in copied.items():
            if not values:
                continue
            p50_idx = max(0, min(len(values) - 1, ceil(len(values) * 0.50) - 1))
            p95_idx = max(0, min(len(values) - 1, ceil(len(values) * 0.95) - 1))
            result[stage] = {
                "count": len(values),
                "p50_ms": round(values[p50_idx], 3),
                "p95_ms": round(values[p95_idx], 3),
                "max_ms": round(values[-1], 3),
            }
        return result

    def reset(self) -> None:
        """Clear samples, primarily for deterministic unit tests."""
        with self._lock:
            self._samples.clear()


LATENCY_METRICS = LatencyRegistry()
