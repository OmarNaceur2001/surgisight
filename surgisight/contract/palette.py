"""Shared color palettes for surgical phases and tools.

Designed for clinical visualization:
- Color-blind friendly (Okabe-Ito / ColorBrewer derived)
- High contrast against dark endoscopic backgrounds
- Shared between backend charts (matplotlib) and frontend (React/CSS/Canvas).
"""

from __future__ import annotations

from typing import Any

# Color palette for 7 surgical phases (P1..P7)
# Hex codes, human names, and suitable contrast text colors
PHASE_PALETTE: dict[str, dict[str, str]] = {
    "P1": {
        "name": "Preparation",
        "hex": "#4E79A7",  # Steel Blue
        "rgba": "rgba(78, 121, 167, 0.85)",
        "light_rgba": "rgba(78, 121, 167, 0.25)",
        "text": "#FFFFFF",
    },
    "P2": {
        "name": "Calot triangle dissection",
        "hex": "#F28E2B",  # Amber Orange
        "rgba": "rgba(242, 142, 43, 0.85)",
        "light_rgba": "rgba(242, 142, 43, 0.25)",
        "text": "#000000",
    },
    "P3": {
        "name": "Clipping and cutting",
        "hex": "#E15759",  # Coral Red
        "rgba": "rgba(225, 87, 89, 0.85)",
        "light_rgba": "rgba(225, 87, 89, 0.25)",
        "text": "#FFFFFF",
    },
    "P4": {
        "name": "Gallbladder dissection",
        "hex": "#76B7B2",  # Teal Sage
        "rgba": "rgba(118, 183, 178, 0.85)",
        "light_rgba": "rgba(118, 183, 178, 0.25)",
        "text": "#000000",
    },
    "P5": {
        "name": "Gallbladder packaging",
        "hex": "#59A14F",  # Emerald Green
        "rgba": "rgba(89, 161, 79, 0.85)",
        "light_rgba": "rgba(89, 161, 79, 0.25)",
        "text": "#FFFFFF",
    },
    "P6": {
        "name": "Cleaning and coagulation",
        "hex": "#EDC948",  # Golden Sand
        "rgba": "rgba(237, 201, 72, 0.85)",
        "light_rgba": "rgba(237, 201, 72, 0.25)",
        "text": "#000000",
    },
    "P7": {
        "name": "Gallbladder retraction",
        "hex": "#B07AA1",  # Dusty Purple
        "rgba": "rgba(176, 122, 161, 0.85)",
        "light_rgba": "rgba(176, 122, 161, 0.25)",
        "text": "#FFFFFF",
    },
}

# Color palette for 7 surgical instruments
TOOL_PALETTE: dict[str, dict[str, str]] = {
    "Grasper": {
        "hex": "#2B83BA",  # Blue
        "rgba": "rgba(43, 131, 186, 0.85)",
    },
    "Bipolar": {
        "hex": "#FDAE61",  # Orange-yellow
        "rgba": "rgba(253, 174, 97, 0.85)",
    },
    "Hook": {
        "hex": "#D7191C",  # Red
        "rgba": "rgba(215, 25, 28, 0.85)",
    },
    "Scissors": {
        "hex": "#ABDDA4",  # Light Green
        "rgba": "rgba(171, 221, 164, 0.85)",
    },
    "Clipper": {
        "hex": "#9E0142",  # Deep Crimson
        "rgba": "rgba(158, 1, 66, 0.85)",
    },
    "Irrigator": {
        "hex": "#5E4FA2",  # Deep Violet
        "rgba": "rgba(94, 79, 162, 0.85)",
    },
    "SpecimenBag": {
        "hex": "#66C2A5",  # Mint Green
        "rgba": "rgba(102, 194, 165, 0.85)",
    },
}

# Hatching pattern configuration for uncertain segments (P5 uncertainty display)
UNCERTAINTY_STYLE: dict[str, Any] = {
    "hatch": "///",
    "stroke_color": "#D32F2F",
    "stroke_width": 2,
    "pattern_color": "rgba(0, 0, 0, 0.35)",
    "label": "uncertain",
}


def get_palette_export() -> dict[str, Any]:
    """Return dictionary suitable for JSON serialization and frontend use."""
    return {
        "phases": PHASE_PALETTE,
        "tools": TOOL_PALETTE,
        "uncertainty": UNCERTAINTY_STYLE,
    }
