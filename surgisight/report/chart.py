"""Matplotlib surgical phase timeline chart renderer."""

from __future__ import annotations

import io
from collections.abc import Sequence

import matplotlib

matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

from surgisight.contract.models import PhaseSegment
from surgisight.contract.palette import PHASE_PALETTE


def render_timeline_chart(
    phases: Sequence[PhaseSegment],
    duration_s: float,
    width_in: float = 7.5,
    height_in: float = 1.4,
    dpi: int = 200,
) -> io.BytesIO:
    """Render a horizontal timeline chart of surgical phases into an in-memory PNG.

    Principle P5 (Uncertainty display): Uncertain segments are drawn with a hatch pattern.
    """
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=dpi)

    total_dur_min = duration_s / 60.0

    # Draw segments
    for seg in phases:
        start_min = seg.start / 60.0
        dur_min = seg.duration_s / 60.0
        phase_key = seg.label.value
        color = PHASE_PALETTE.get(phase_key, {}).get("hex", "#7F7F7F")

        # Hatched pattern for uncertain predictions (P5)
        hatch = "//" if seg.uncertain else None
        alpha = 0.65 if seg.uncertain else 0.95

        rect = mpatches.Rectangle(
            (start_min, 0.2),
            dur_min,
            0.6,
            facecolor=color,
            edgecolor="#2C3E50",
            linewidth=0.8,
            hatch=hatch,
            alpha=alpha,
        )
        ax.add_patch(rect)

        # Label inside block if wide enough
        if dur_min > total_dur_min * 0.05:
            mid_min = start_min + dur_min / 2.0
            text_color = PHASE_PALETTE.get(phase_key, {}).get("text", "#000000")
            label_text = f"{phase_key}*" if seg.uncertain else phase_key
            ax.text(
                mid_min,
                0.5,
                label_text,
                ha="center",
                va="center",
                color=text_color,
                fontsize=8,
                fontweight="bold",
            )

    ax.set_xlim(0, max(1.0, total_dur_min))
    ax.set_ylim(0, 1.0)
    ax.set_yticks([])
    ax.set_xlabel("Procedure Time (minutes)", fontsize=8, labelpad=4)

    # Style axes
    ax.spines["top"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color("#BDC3C7")
    ax.tick_params(axis="x", labelsize=8, colors="#34495E")

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
