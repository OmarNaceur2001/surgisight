"""Confidence calibration utilities and uncertainty assessment."""

from __future__ import annotations

import numpy as np


def apply_temperature_scaling(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    """Scale logits by temperature parameter T > 0 and return softmax probabilities."""
    t = max(1e-4, float(temperature))
    scaled = logits / t
    exp_scaled = np.exp(scaled - np.max(scaled, axis=-1, keepdims=True))
    return exp_scaled / np.sum(exp_scaled, axis=-1, keepdims=True)


def compute_expected_calibration_error(
    confidences: np.ndarray,
    accuracies: np.ndarray,
    num_bins: int = 10,
) -> float:
    """Compute Expected Calibration Error (ECE) across confidences and binary accuracies.

    Args:
        confidences: 1D array of predicted class confidences in [0, 1].
        accuracies: 1D array of binary ground-truth matches (1 if correct, 0 otherwise).
        num_bins: Number of equal-width probability bins.

    Returns:
        ECE value in [0, 1].
    """
    if len(confidences) == 0:
        return 0.0

    bins = np.linspace(0.0, 1.0, num_bins + 1)
    ece = 0.0
    total_samples = len(confidences)

    for i in range(num_bins):
        bin_lower = bins[i]
        bin_upper = bins[i + 1]

        mask = (
            (confidences >= bin_lower) & (confidences < bin_upper)
            if i < num_bins - 1
            else (confidences >= bin_lower) & (confidences <= bin_upper)
        )
        bin_size = np.sum(mask)

        if bin_size > 0:
            bin_acc = np.mean(accuracies[mask])
            bin_conf = np.mean(confidences[mask])
            ece += (bin_size / total_samples) * abs(bin_acc - bin_conf)

    return float(ece)


def is_uncertain(confidence: float, threshold: float = 0.50) -> bool:
    """Evaluate whether confidence score falls below the calibrated uncertainty threshold."""
    return float(confidence) < float(threshold)
