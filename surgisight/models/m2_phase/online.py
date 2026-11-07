"""Online causal phase recognition pipeline (M2).

Designed for strictly online, causal inference at 1 Hz with a bounded ring buffer.
Supports execution on CPU with zero future lookahead.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

from surgisight.contract.types import PhaseId, ToolId
from surgisight.data.transforms import frame_transform

PHASES: tuple[PhaseId, ...] = (
    PhaseId.P1,
    PhaseId.P2,
    PhaseId.P3,
    PhaseId.P4,
    PhaseId.P5,
    PhaseId.P6,
    PhaseId.P7,
)

TOOLS: tuple[ToolId, ...] = (
    ToolId.GRASPER,
    ToolId.BIPOLAR,
    ToolId.HOOK,
    ToolId.SCISSORS,
    ToolId.CLIPPER,
    ToolId.IRRIGATOR,
    ToolId.SPECIMEN_BAG,
)


class OnlinePhasePipeline:
    """Online, causal phase prediction pipeline with bounded temporal ring buffer."""

    def __init__(
        self,
        config: dict[str, Any],
        weights: dict[str, Any] | None = None,
        device: str = "cpu",
        max_buffer_size: int = 300,
    ) -> None:
        self.config = config
        self.weights = weights or {}
        self.device = device
        self.max_buffer_size = max_buffer_size
        self.ring_buffer: deque[np.ndarray] = deque(maxlen=max_buffer_size)
        self.hidden_state: np.ndarray | None = None

        # Feature projection parameters
        self.feature_dim = config.get("feature_dim", 64)
        self.num_phases = len(PHASES)
        self.num_tools = len(TOOLS)

        # Transition matrix prior if available
        self.transition_matrix = self.weights.get("transition_matrix")
        if self.transition_matrix is None:
            # Default identity-biased transition matrix
            self.transition_matrix = np.eye(self.num_phases) * 0.95 + 0.05 / self.num_phases

    def reset(self) -> None:
        """Reset internal temporal state and ring buffer."""
        self.ring_buffer.clear()
        self.hidden_state = None

    def get_buffer_size(self) -> int:
        """Return current length of the ring buffer."""
        return len(self.ring_buffer)

    def extract_features(self, frame: np.ndarray) -> np.ndarray:
        """Extract spatial feature vector from transformed frame."""
        transformed = frame_transform(frame)  # (3, 224, 224) float32

        # If projection weights provided, use linear projection
        w_proj = self.weights.get("w_proj")
        if w_proj is not None:
            # Flatten spatial downsampling: 8x8 patches across channels
            downsampled = transformed[:, ::28, ::28].flatten()  # 3*8*8 = 192
            if downsampled.shape[0] != w_proj.shape[0]:
                downsampled = np.resize(downsampled, (w_proj.shape[0],))
            feat = downsampled @ w_proj
        else:
            # Deterministic, lightweight visual feature extraction without torch
            # Spatial grid averages + channel statistics
            grid = transformed.mean(axis=0)[::28, ::28].flatten()  # 64 values
            feat = grid[: self.feature_dim]
            if len(feat) < self.feature_dim:
                feat = np.pad(feat, (0, self.feature_dim - len(feat)))

        # Normalize feature vector
        norm = np.linalg.norm(feat)
        if norm > 1e-6:
            feat = feat / norm
        return feat.astype(np.float32)

    def step(
        self,
        frame_rgb_uint8_cropped: np.ndarray,
        t: float,
        frame_idx: int | None = None,
    ) -> dict[str, Any]:
        """Execute one online causal inference step for a 1 Hz frame.

        Args:
            frame_rgb_uint8_cropped: uint8 RGB image (H, W, 3).
            t: Timestamp in seconds from video start.
            frame_idx: Optional source video frame index.

        Returns:
            Dictionary conforming to Data Contract v1.0 PerSecondRecord.
        """
        # 1. Feature extraction
        feat = self.extract_features(frame_rgb_uint8_cropped)

        # 2. Add to bounded ring buffer (FIFO)
        self.ring_buffer.append(feat)

        # 3. Causal temporal convolution / exponential smoothing
        # Weight recent frames exponentially higher, strictly causal (past to current)
        buffer_len = len(self.ring_buffer)
        decay = float(self.config.get("temporal_decay", 0.85))
        weights = np.array(
            [decay ** (buffer_len - 1 - i) for i in range(buffer_len)], dtype=np.float32
        )
        weights /= weights.sum()

        temporal_feat = np.zeros(self.feature_dim, dtype=np.float32)
        for i, past_feat in enumerate(self.ring_buffer):
            temporal_feat += weights[i] * past_feat

        # 4. Phase logit computation
        w_phase = self.weights.get("w_phase")
        if w_phase is not None:
            logits = temporal_feat @ w_phase
        else:
            # Synthetic/deterministic heuristic based on progress & features
            logits = np.zeros(self.num_phases, dtype=np.float32)
            # Prior progress signal if duration known or time-based
            phase_idx = int(min(6, max(0, int(t / 60.0))))
            logits[phase_idx] += 2.0
            # Add feature modulation
            logits += temporal_feat[: self.num_phases]

        # Transition matrix smoothing if hidden state exists
        if self.hidden_state is not None:
            prior_probs = self.hidden_state @ self.transition_matrix
            logits = logits * 0.7 + np.log(np.maximum(prior_probs, 1e-6)) * 0.3

        # Numerically stable softmax
        exp_logits = np.exp(logits - np.max(logits))
        phase_probs = exp_logits / exp_logits.sum()
        self.hidden_state = phase_probs

        selected_phase_idx = int(np.argmax(phase_probs))
        phase_label = PHASES[selected_phase_idx]

        # 5. Tool presence probabilities
        w_tools = self.weights.get("w_tools")
        if w_tools is not None:
            tool_logits = temporal_feat @ w_tools
            tool_probs = 1.0 / (1.0 + np.exp(-tool_logits))
        else:
            # Baseline tool presence probabilities correlated with phase
            base_tool_map: dict[PhaseId, list[float]] = {
                PhaseId.P1: [0.60, 0.05, 0.05, 0.02, 0.01, 0.05, 0.01],
                PhaseId.P2: [0.75, 0.35, 0.65, 0.10, 0.05, 0.15, 0.01],
                PhaseId.P3: [0.65, 0.15, 0.20, 0.40, 0.85, 0.10, 0.01],
                PhaseId.P4: [0.70, 0.45, 0.80, 0.10, 0.05, 0.20, 0.01],
                PhaseId.P5: [0.60, 0.05, 0.05, 0.05, 0.02, 0.15, 0.90],
                PhaseId.P6: [0.50, 0.55, 0.30, 0.05, 0.02, 0.70, 0.10],
                PhaseId.P7: [0.55, 0.05, 0.05, 0.02, 0.01, 0.10, 0.30],
            }
            tool_probs = np.array(
                base_tool_map.get(phase_label, [0.1] * self.num_tools), dtype=np.float32
            )

        return {
            "t": round(float(t), 2),
            "frame_idx": frame_idx,
            "phase": {
                "label": phase_label.value,
                "probs": [round(float(p), 4) for p in phase_probs],
            },
            "tools": [round(float(p), 4) for p in tool_probs],
            "triplets": [],
            "quality_flags": [],
        }


def load_pipeline(
    artifact_dir: str | Path,
    device: str = "cpu",
) -> tuple[OnlinePhasePipeline, dict[str, Any]]:
    """Load an exported online phase pipeline from an artifact folder.

    Expected artifact folder structure:
    - config.json (pipeline architecture and hyperparameters)
    - model_card.json (metadata, performance, licensing, synthetic flags)
    - transition.npy (optional transition probability matrix)
    - weights.npz or weights.npy (projection and head weights)
    """
    path = Path(artifact_dir)
    if not path.is_dir():
        raise FileNotFoundError(f"Artifact directory does not exist: {path}")

    config_path = path / "config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing config.json in artifact dir: {path}")

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    weights: dict[str, Any] = {}

    # Load transition matrix if present
    transition_path = path / "transition.npy"
    if transition_path.is_file():
        weights["transition_matrix"] = np.load(transition_path)

    # Load weights if present (numpy weights supported natively without torch)
    weights_npz = path / "weights.npz"
    if weights_npz.is_file():
        npz = np.load(weights_npz)
        for k in npz.files:
            weights[k] = npz[k]

    # Optional torch loading if .pt files exist and torch is installed
    backbone_pt = path / "backbone.pt"
    if backbone_pt.is_file():
        try:
            import torch

            weights["backbone_state"] = torch.load(backbone_pt, map_location=device)
        except ImportError:
            pass

    max_buffer_size = int(config.get("max_buffer_size", 300))
    pipeline = OnlinePhasePipeline(
        config=config,
        weights=weights,
        device=device,
        max_buffer_size=max_buffer_size,
    )
    return pipeline, config
