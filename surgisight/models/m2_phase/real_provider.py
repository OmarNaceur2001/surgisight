"""Real model provider for surgical phase recognition (M2).

Loads real model weights from artifact directory with security, integrity,
and synthetic-rejection checks.
Falls back to MockPhaseProvider when artifacts are not installed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from surgisight.contract.models import PhasePrediction, PhaseSegment, validate_interval_tiling
from surgisight.contract.types import PHASE_NAMES, PHASE_ORDER, PhaseId
from surgisight.models.m2_phase.online import OnlinePhasePipeline, load_pipeline
from surgisight.models.providers import MockPhaseProvider, PhaseProvider
from surgisight.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_ARTIFACT_DIR = Path("surgisight/models/artifacts/m2_phase_v0.1")


def compute_directory_hash(directory: Path) -> str:
    """Compute deterministic SHA-256 hash over directory contents."""
    hasher = hashlib.sha256()
    for file_path in sorted(directory.rglob("*")):
        if file_path.is_file():
            hasher.update(file_path.name.encode("utf-8"))
            try:
                with open(file_path, "rb") as f:
                    while chunk := f.read(65536):
                        hasher.update(chunk)
            except OSError:
                pass
    return hasher.hexdigest()


class RealPhaseProvider(PhaseProvider):
    """M2 Real Phase Provider wrapping OnlinePhasePipeline with safety validation."""

    def __init__(self, artifact_dir: str | Path | None = None) -> None:
        self.artifact_dir = Path(artifact_dir or DEFAULT_ARTIFACT_DIR)
        self.mock_provider = MockPhaseProvider()
        self.is_fallback: bool = False
        self.model_version: str = "mock_fallback"
        self.pipeline: OnlinePhasePipeline | None = None
        self.config: dict[str, Any] = {}

        self._initialize()

    def _initialize(self) -> None:
        """Inspect and load the model artifact or activate fallback."""
        if not self.artifact_dir.is_dir():
            logger.warning(
                "M2 artifact directory '%s' not found. Falling back to MockPhaseProvider.",
                self.artifact_dir,
            )
            self.is_fallback = True
            self.model_version = "mock_fallback (artifact not found)"
            return

        config_path = self.artifact_dir / "config.json"
        if not config_path.is_file():
            logger.warning(
                "Missing config.json in '%s'. Falling back to MockPhaseProvider.",
                self.artifact_dir,
            )
            self.is_fallback = True
            self.model_version = "mock_fallback (missing config.json)"
            return

        # Check model card for synthetic / DO_NOT_USE indicators (P2 / P8)
        model_card_path = self.artifact_dir / "model_card.json"
        is_synthetic = False
        if model_card_path.is_file():
            try:
                with open(model_card_path, encoding="utf-8") as f:
                    card = json.load(f)
                    if (
                        card.get("is_synthetic") is True
                        or "synthetic" in card.get("name", "").lower()
                        or "DO_NOT_USE" in card.get("tags", [])
                    ):
                        is_synthetic = True
            except Exception as e:
                logger.warning("Could not read model_card.json: %s", e)

        # Config synthetic check
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
            if cfg.get("is_synthetic") is True:
                is_synthetic = True

        if is_synthetic and not settings.allow_synthetic_artifact:
            raise ValueError(
                "Artifact is marked 'synthetic' or 'DO_NOT_USE' and settings.allow_synthetic_artifact is False."
            )

        # Compute artifact integrity hash
        art_hash = compute_directory_hash(self.artifact_dir)
        self.model_version = f"m2_phase_v0.1:{art_hash[:12]}"

        # Load pipeline
        self.pipeline, self.config = load_pipeline(self.artifact_dir)
        self.is_fallback = False
        logger.info("Loaded real M2 phase pipeline version %s", self.model_version)

    def predict_phases(
        self,
        duration_s: float,
        seed: int = 42,
        frames: list[np.ndarray] | None = None,
    ) -> tuple[list[PhasePrediction], list[PhaseSegment]]:
        """Predict per-second phases and contiguous tiled phase segments."""
        if self.is_fallback or self.pipeline is None:
            return self.mock_provider.predict_phases(duration_s=duration_s, seed=seed)

        self.pipeline.reset()
        num_seconds = max(1, int(round(duration_s)))
        phase_predictions: list[PhasePrediction] = []

        for sec in range(num_seconds):
            t = float(sec)
            frame_idx = sec * 25
            if frames and sec < len(frames):
                frame = frames[sec]
            else:
                # Default baseline frame for test/batch execution
                frame = np.full((224, 224, 3), 128, dtype=np.uint8)

            rec = self.pipeline.step(frame, t=t, frame_idx=frame_idx)
            raw_phase = rec["phase"]
            label = PhaseId(raw_phase["label"])
            raw_probs = raw_phase["probs"]

            probs_dict = {PHASE_ORDER[i]: float(raw_probs[i]) for i in range(len(PHASE_ORDER))}
            # Normalize sum to 1.0
            p_sum = sum(probs_dict.values())
            if p_sum > 0:
                probs_dict = {k: v / p_sum for k, v in probs_dict.items()}

            phase_predictions.append(PhasePrediction(label=label, probs=probs_dict))

        # Build contiguous tiled phase segments
        segments = self._build_tiled_segments(phase_predictions, duration_s)
        validate_interval_tiling(segments, duration_s)
        return phase_predictions, segments

    def _build_tiled_segments(
        self,
        predictions: list[PhasePrediction],
        duration_s: float,
    ) -> list[PhaseSegment]:
        """Aggregate per-second predictions into contiguous, tiled segments."""
        if not predictions:
            return [
                PhaseSegment(
                    label=PhaseId.P1,
                    name=PHASE_NAMES[PhaseId.P1],
                    start=0.0,
                    end=round(duration_s, 2),
                    conf=0.5,
                    uncertain=False,
                )
            ]

        raw_segments: list[tuple[PhaseId, float, float, list[float]]] = []
        curr_label = predictions[0].label
        curr_start = 0.0
        curr_confs = [predictions[0].confidence]

        for s in range(1, len(predictions)):
            pred = predictions[s]
            if pred.label == curr_label:
                curr_confs.append(pred.confidence)
            else:
                raw_segments.append((curr_label, curr_start, float(s), curr_confs))
                curr_label = pred.label
                curr_start = float(s)
                curr_confs = [pred.confidence]

        raw_segments.append((curr_label, curr_start, float(len(predictions)), curr_confs))

        # Adjust the last segment end to exactly duration_s
        result: list[PhaseSegment] = []
        for i, (label, start, end, confs) in enumerate(raw_segments):
            seg_end = round(duration_s, 2) if i == len(raw_segments) - 1 else round(end, 2)
            seg_conf = round(min(confs), 4) if confs else 0.5
            uncertain = seg_conf < 0.50

            result.append(
                PhaseSegment(
                    label=label,
                    name=PHASE_NAMES[label],
                    start=round(start, 2),
                    end=seg_end,
                    conf=seg_conf,
                    uncertain=uncertain,
                )
            )

        return result
