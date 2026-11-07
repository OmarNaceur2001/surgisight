"""Synthetic 90-minute online M2 memory/throughput harness."""
from __future__ import annotations
import argparse
import ctypes
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def create_pipeline(max_buffer_size: int) -> Any:
    """Import the project pipeline after ensuring the repository root is importable."""
    sys.path.insert(0, str(ROOT))
    from surgisight.models.m2_phase.online import OnlinePhasePipeline

    return OnlinePhasePipeline(
        config={"feature_dim": 64, "temporal_decay": 0.85},
        max_buffer_size=max_buffer_size,
    )

def process_rss_bytes() -> int:
    """Return current process RSS using Windows API or Linux procfs."""
    if os.name == "nt":
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        if not ok:
            raise OSError("GetProcessMemoryInfo failed")
        return int(counters.WorkingSetSize)
    statm = Path("/proc/self/statm").read_text(encoding="ascii").split()
    return int(statm[1]) * os.sysconf("SC_PAGE_SIZE")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=5400)
    parser.add_argument("--warmup", type=int, default=60)
    parser.add_argument("--max-buffer", type=int, default=300)
    parser.add_argument("--max-growth-pct", type=float, default=5.0)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    if args.seconds <= args.warmup or args.warmup < 1 or args.max_buffer < 1:
        parser.error("seconds must exceed warmup; warmup and max-buffer must be positive")
    rng = np.random.default_rng(2026)
    frame = rng.integers(0, 256, size=(224, 224, 3), dtype=np.uint8)
    pipeline = OnlinePhasePipeline(config={"feature_dim": 64, "temporal_decay": 0.85}, max_buffer_size=args.max_buffer)
    started = time.perf_counter()
    for index in range(args.warmup):
        pipeline.step(frame, t=float(index), frame_idx=index * 25)
    baseline = process_rss_bytes()
    for index in range(args.warmup, args.seconds):
        pipeline.step(frame, t=float(index), frame_idx=index * 25)
    elapsed = time.perf_counter() - started
    final = process_rss_bytes()
    growth_pct = ((final - baseline) / baseline * 100.0) if baseline else 0.0
    bounded = pipeline.get_buffer_size() <= args.max_buffer
    print(f"steps={args.seconds} warmup={args.warmup} seconds_elapsed={elapsed:.3f}")
    print(f"buffer_size={pipeline.get_buffer_size()} buffer_limit={args.max_buffer}")
    print(f"rss_start_bytes={baseline} rss_end_bytes={final} rss_growth_pct={growth_pct:.3f}")
    print("frames=synthetic; model_weights=not_loaded; data=none")
    passed = bounded and growth_pct <= args.max_growth_pct
    print(f"memory_gate={'PASS' if passed else 'FAIL'} threshold_pct={args.max_growth_pct}")
    return 1 if args.enforce and not passed else 0

if __name__ == "__main__":
    raise SystemExit(main())
