#!/usr/bin/env python3
"""Shared color palette for all ACBench paper figures (and matched to the draw.io diagrams).

Shared anchors with figure-specific, explicitly labeled roles:
  BLUE  #1A80BB  -> ER / candidate-feedback contrasts / passing speedups
  RED   #A00000  -> application failures / outer-retry path
  GRAY  #B0B7C3  -> NR / neutral context (darker gray for baseline-profile contrasts)

A blue contrast does not by itself mean an improvement. Marker shapes, labels,
and zero lines explain the comparison independently of color.

Import and call apply_style() once, then use the named colors / ramps.
"""
from __future__ import annotations

# --- anchors ---
BLUE = "#1A80BB"   # primary comparison / ER / passing speedup
RED  = "#A00000"   # failure / outer retry
GRAY = "#B0B7C3"   # neutral baseline / none / OFF

# --- sequential relatives (tints toward white, shades toward black) ---
BLUE_LIGHT = "#8DBEDE"
BLUE_DARK  = "#104D70"
RED_LIGHT  = "#D87C7C"
RED_DARK   = "#600000"
GRAY_DARK  = "#6B7280"

# ordinal quality ramp, worst -> best (red -> blue). e.g. outcome funnel:
# not-applied, broke-tests, tests-pass/no-speedup, tests-pass/faster
RAMP4 = [RED, RED_LIGHT, BLUE_LIGHT, BLUE]

# categorical cycle for multi-series plots (anchors first, then their relatives)
CYCLE = [BLUE, RED, GRAY_DARK, BLUE_DARK, RED_LIGHT, BLUE_LIGHT]


def _cmaps():
    import matplotlib.colors as mcolors
    seq_blue = mcolors.LinearSegmentedColormap.from_list("acb_blue", ["#EAF3F9", BLUE, BLUE_DARK])
    seq_red  = mcolors.LinearSegmentedColormap.from_list("acb_red",  ["#F7E9E9", RED, RED_DARK])
    # diverging for signed contrasts (negative=red, 0=light, positive=blue)
    diverging = mcolors.LinearSegmentedColormap.from_list(
        "acb_div", [RED_DARK, RED, "#F2F2F2", BLUE, BLUE_DARK])
    return seq_blue, seq_red, diverging


SEQ_BLUE, SEQ_RED, DIVERGING = _cmaps()


def apply_style():
    """Set matplotlib rcParams so every figure shares fonts, spines and the color cycle."""
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "axes.prop_cycle": plt.cycler(color=CYCLE),
        "axes.edgecolor": "#333333",
        "axes.linewidth": 0.75,
        "axes.labelcolor": "#1a1a1a",
        "axes.titlecolor": "#1a1a1a",
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.color": "#333333",
        "ytick.color": "#333333",
        "xtick.major.width": 0.75,
        "ytick.major.width": 0.75,
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 10,
        "legend.frameon": False,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
        "axes.unicode_minus": True,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
    })
