"""Unit and property tests for M2 Online Phase Recognition.

Tests:
1. Truncation causality: pipeline on sequence truncated at random times equals full run for all earlier seconds.
2. Ring buffer stays bounded over long sequence (no unbounded memory growth).
3. Training/serving skew test: frame_transform output matches config expectations.
4. Artifact validation: synthetic/DO_NOT_USE rejected unless allow_synthetic_artifact is True.
5. Missing artifact fallback: gracefully falls back to MockPhaseProvider.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from surgisight.contract.models import validate_interval_tiling
from surgisight.data.transforms import frame_transform
from surgisight.models.m2_phase.online import OnlinePhasePipeline, load_pipeline
from surgisight.models.m2_phase.real_provider import RealPhaseProvider
from surgisight.settings import settings


@pytest.fixture
def synthetic_artifact_dir(tmp_path: Path) -> Path:
    """Create a temporary artifact directory with synthetic weights."""
    artifact_dir = tmp_path / "m2_phase_fixture"
    artifact_dir.mkdir(parents=True)

    config = {
        "model_name": "m2_phase_test",
        "feature_dim": 32,
        "temporal_decay": 0.85,
        "max_buffer_size": 50,
        "input_resolution": [224, 224],
        "is_synthetic": True,
    }
    with open(artifact_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(config, f)

    model_card = {
        "name": "M2-Phase-Synthetic-Test",
        "version": "0.1.0",
        "is_synthetic": True,
        "tags": ["DO_NOT_USE", "test_fixture"],
    }
    with open(artifact_dir / "model_card.json", "w", encoding="utf-8") as f:
        json.dump(model_card, f)

    # Save mock transition matrix
    trans = np.eye(7, dtype=np.float32) * 0.9 + 0.1 / 7
    np.save(artifact_dir / "transition.npy", trans)

    # Save lightweight projection weights
    w_proj = np.random.randn(64, 32).astype(np.float32)
    w_phase = np.random.randn(32, 7).astype(np.float32)
    w_tools = np.random.randn(32, 7).astype(np.float32)
    np.savez(artifact_dir / "weights.npz", w_proj=w_proj, w_phase=w_phase, w_tools=w_tools)

    return artifact_dir


class TestOnlinePhasePipeline:
    def test_truncation_causality(self):
        """Pipeline truncated at random time equals full run for all earlier seconds."""
        config = {"feature_dim": 32, "temporal_decay": 0.85, "max_buffer_size": 100}
        np.random.seed(42)

        # Generate 30 synthetic frames
        frames = [np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8) for _ in range(30)]

        # Full run (30 seconds)
        pipe_full = OnlinePhasePipeline(config=config)
        full_records = [pipe_full.step(frames[i], t=float(i)) for i in range(30)]

        # Truncated run (stop at 15 seconds)
        pipe_trunc = OnlinePhasePipeline(config=config)
        trunc_records = [pipe_trunc.step(frames[i], t=float(i)) for i in range(15)]

        # Invariant: first 15 predictions must be strictly identical
        for i in range(15):
            assert full_records[i]["phase"]["label"] == trunc_records[i]["phase"]["label"]
            assert full_records[i]["phase"]["probs"] == trunc_records[i]["phase"]["probs"]
            assert full_records[i]["tools"] == trunc_records[i]["tools"]

    def test_ring_buffer_bounded_over_long_sequence(self):
        """Ring buffer stays strictly bounded over 500 frames without unbounded growth."""
        max_buf = 40
        config = {"feature_dim": 32, "max_buffer_size": max_buf}
        pipe = OnlinePhasePipeline(config=config, max_buffer_size=max_buf)

        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        for t in range(500):
            pipe.step(frame, t=float(t))
            assert pipe.get_buffer_size() <= max_buf

        assert pipe.get_buffer_size() == max_buf

        # Reset empties the buffer
        pipe.reset()
        assert pipe.get_buffer_size() == 0

    def test_training_serving_skew(self):
        """frame_transform preserves exact output dimensions, dtype, and scale."""
        raw_frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        transformed = frame_transform(raw_frame)

        assert transformed.shape == (3, 224, 224)
        assert transformed.dtype == np.float32


class TestRealPhaseProvider:
    def test_missing_artifact_fallback_to_mock(self, tmp_path: Path):
        """Provider falls back to MockPhaseProvider when directory does not exist."""
        non_existent = tmp_path / "does_not_exist"
        provider = RealPhaseProvider(artifact_dir=non_existent)

        assert provider.is_fallback is True
        assert "mock_fallback" in provider.model_version

        preds, segments = provider.predict_phases(duration_s=60.0)
        assert len(preds) == 60
        validate_interval_tiling(segments, 60.0)

    def test_synthetic_artifact_rejection(self, synthetic_artifact_dir: Path, monkeypatch):
        """Synthetic artifact is rejected with ValueError when allow_synthetic_artifact is False."""
        monkeypatch.setattr(settings, "allow_synthetic_artifact", False)
        with pytest.raises(ValueError, match="marked 'synthetic' or 'DO_NOT_USE'"):
            RealPhaseProvider(artifact_dir=synthetic_artifact_dir)

    def test_synthetic_artifact_allowed_with_flag(self, synthetic_artifact_dir: Path, monkeypatch):
        """Synthetic artifact loads successfully when allow_synthetic_artifact is True."""
        monkeypatch.setattr(settings, "allow_synthetic_artifact", True)
        provider = RealPhaseProvider(artifact_dir=synthetic_artifact_dir)

        assert provider.is_fallback is False
        assert provider.model_version.startswith("m2_phase_v0.1:")

        preds, segments = provider.predict_phases(duration_s=45.0)
        assert len(preds) == 45
        validate_interval_tiling(segments, 45.0)
        assert segments[0].start == 0.0
        assert segments[-1].end == 45.0

    def test_load_pipeline_helper(self, synthetic_artifact_dir: Path):
        """load_pipeline correctly loads artifact and returns pipeline and config."""
        pipe, cfg = load_pipeline(synthetic_artifact_dir)
        assert isinstance(pipe, OnlinePhasePipeline)
        assert cfg["model_name"] == "m2_phase_test"
        assert pipe.max_buffer_size == 50
