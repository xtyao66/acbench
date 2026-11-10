#!/usr/bin/env python3
"""Tier-1 paper figures for the perf panel, sourced from analyze_fleet (single source of truth).

Produces matching copies in this artifact's results/figs/:
  fig_apply_lift.{png,pdf,svg}  matched NR/GR/ER rates plus direct ER-GR effects
  fig_funnel.{png,pdf,svg}      retry outcomes and speedup-cutoff sensitivity
  fig_retry_shift.{png,pdf,svg} outcome-rate contrasts with scenario intervals
  fig_fidelity.{png,pdf,svg}    contrasts with raw/family-wise intervals

Apply-lift and funnel charts use the seven models with both OFF and ON rows. The
fidelity chart uses the full OFF fidelity panel through fid_rigor.py. Figure 1
is maintained as diagrams/fig_scaffold.drawio so it remains editable.
Run: python3 make_panel_figures.py
"""
from __future__ import annotations
import math
import os, sys
import shutil
sys.path.insert(0, os.path.dirname(__file__))
from analyze_fleet import build_data, funnel, EXP_SCEN  # noqa: E402
from fid_data import tidy  # noqa: E402
from fid_rigor import f3_common_panel_results  # noqa: E402
from retry_sensitivity import (  # noqa: E402
    matched_retry_panel, model_outcome_effects, retry_apply_effects,
    scenario_balanced_outcomes,
)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
import acbench_palette as pal  # noqa: E402
pal.apply_style()

ROOT = os.path.dirname(__file__)
FIGDIRS = [os.path.join(ROOT, "results", "figs")]
for directory in FIGDIRS:
    os.makedirs(directory, exist_ok=True)
SHORT = {"gpt-oss-120b": "oss-120b", "gpt-oss-20b": "oss-20b", "v4-flash": "V4-Flash",
         "qwen3-235b": "Qwen3-235B", "qwen3.5": "Qwen3.5", "glm-5.2": "GLM-5.2",
         "deepseek-v4-pro": "V4-Pro", "kimi-k2.6": "Kimi-K2.6",
         "devstral": "Devstral", "llama-4-maverick": "Llama-4",
         "minimax-m3": "MiniMax-M3", "qwen3-coder": "Qwen3-Coder"}

# Seven models with both arms available for the F1/F2 panel.
PANEL = ["devstral", "gpt-oss-120b", "gpt-oss-20b", "llama-4-maverick",
         "qwen3-235b", "qwen3.5", "v4-flash"]
def _save(fig, name):
    for ext in ("png", "pdf", "svg"):
        path = os.path.join(FIGDIRS[0], f"{name}.{ext}")
        fig.savefig(path, dpi=450, bbox_inches="tight", pad_inches=0.025)
        for directory in FIGDIRS[1:]:
            shutil.copyfile(path, os.path.join(directory, f"{name}.{ext}"))
    plt.close(fig)
    print(f"  wrote {name}.png/.pdf/.svg")


def complete(data, model, cond):
    r = data.get((model, cond))
    return r if r and len({x["scenario_id"] for x in r}) >= EXP_SCEN else None


def _wilson(k, n, z=1.96):
    """Wilson score interval for a binomial proportion."""
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return center - half, center + half


def _stripe_rows(ax, positions):
    """Add subtle alternating guides without competing with the data."""
    for i, yy in enumerate(positions):
        if i % 2:
            ax.axhspan(yy - 0.48, yy + 0.48, color="#F5F8FA", zorder=0)


def _legacy_fig_scaffold_matplotlib():
    """Legacy fallback; Figure 1 is maintained in editable Draw.io form."""
    fig, ax = plt.subplots(figsize=(3.45, 1.86))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    def box(x, y, w, h, label, face, edge, fontsize=5.8, weight="normal"):
        patch = FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.012,rounding_size=0.018",
            linewidth=0.9, facecolor=face, edgecolor=edge, zorder=3,
        )
        ax.add_patch(patch)
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                fontsize=fontsize, color="#1A1A1A", fontweight=weight,
                linespacing=1.05, zorder=4)
        return (x, y, w, h)

    def arrow(start, end, color=pal.GRAY_DARK, style="-", curve=None, width=0.9):
        ax.add_patch(FancyArrowPatch(
            start, end, arrowstyle="-|>", mutation_scale=7.5,
            linewidth=width, linestyle=style, color=color,
            connectionstyle=curve or "arc3", shrinkA=1.5, shrinkB=1.5,
            zorder=2,
        ))

    base = box(0.015, 0.59, 0.14, 0.18, "clean\nbaseline", "#F5F8FA", pal.GRAY_DARK,
               weight="bold")
    model = box(0.195, 0.59, 0.15, 0.18, "propose\npatch", "#EAF3F9", pal.BLUE_DARK,
                weight="bold")
    inner = box(0.385, 0.55, 0.20, 0.26, "validate diff\nrepair format\n(max 2)", "#EAF3F9",
                pal.BLUE_DARK, fontsize=5.05)
    apply = box(0.625, 0.59, 0.13, 0.18, "apply\npatch", "#F5F8FA", pal.GRAY_DARK,
                weight="bold")
    retry = box(0.79, 0.52, 0.195, 0.32,
                "outer policy\nNR: stop\nGR: generic retry\nER: retry + error*",
                "#F7E9E9", pal.RED, fontsize=4.5)
    test = box(0.58, 0.18, 0.195, 0.20, "test +\nbenchmark", "#EAF3F9", pal.BLUE,
               fontsize=5.45, weight="bold")
    feedback = box(0.80, 0.18, 0.185, 0.20, "feedback for\nnext round", "#EAF3F9", pal.BLUE_DARK,
                   fontsize=5.2)

    arrow((base[0] + base[2], 0.68), (model[0], 0.68))
    arrow((model[0] + model[2], 0.68), (inner[0], 0.68), color=pal.BLUE_DARK)
    arrow((inner[0] + inner[2], 0.68), (apply[0], 0.68), color=pal.BLUE_DARK)
    arrow((apply[0] + apply[2], 0.70), (retry[0], 0.70), color=pal.RED)
    ax.text(0.772, 0.75, "not applied", ha="right", va="center", fontsize=4.35,
            color=pal.RED_DARK)
    arrow((apply[0] + apply[2] / 2, apply[1]),
          (test[0] + test[2] / 2, test[1] + test[3]), color=pal.BLUE)
    ax.text(0.71, 0.47, "applied", ha="left", va="center", fontsize=4.85,
            color=pal.BLUE_DARK)
    arrow((test[0] + test[2], 0.28), (feedback[0], 0.28), color=pal.BLUE)

    arrow((retry[0] + retry[2] / 2, retry[1] + retry[3]),
          (model[0] + model[2] / 2, model[1] + model[3]),
          color=pal.RED, style="--", curve="arc3,rad=0.26", width=0.85)
    ax.text(0.59, 0.92, "outer retry: same source, new sample", ha="center", va="center",
            fontsize=5.0, color=pal.RED_DARK)
    ax.text(0.888, 0.455, "*parser error, if available", ha="center", va="center",
            fontsize=4.1, color=pal.RED_DARK)
    ax.plot([feedback[0] + feedback[2] / 2, feedback[0] + feedback[2] / 2, base[0] + 0.07],
            [feedback[1], 0.075, 0.075], color=pal.BLUE_DARK, lw=0.85,
            ls="--", zorder=1)
    arrow((base[0] + 0.07, 0.075), (base[0] + 0.07, base[1]),
          color=pal.BLUE_DARK, style="--", width=0.85)
    ax.text(0.49, 0.025, "next round: clean tree + prior feedback", ha="center", va="center",
            fontsize=5.0, color=pal.BLUE_DARK)
    _save(fig, "fig_scaffold")


def fig_apply_lift(data):
    control = retry_apply_effects(matched_retry_panel(data))
    rows = sorted(control["rows"], key=lambda row: row["effect"][0], reverse=True)
    rows.append(dict(model="__pooled__", **control["pooled"]))
    y = list(range(len(rows) - 1)) + [len(rows) - 0.35]
    fig, (ax_rate, ax_effect) = plt.subplots(
        1, 2, figsize=(3.5, 2.30), sharey=True,
        gridspec_kw={"width_ratios": [1.35, 1.0], "wspace": 0.13},
    )
    for ax in (ax_rate, ax_effect):
        _stripe_rows(ax, y[:-1])
        ax.axhspan(y[-1] - 0.48, y[-1] + 0.48, color="#EAF1F6", zorder=0)
    style = {
        "NR": dict(marker="o", color=pal.GRAY_DARK, face="white", label="NR"),
        "GR": dict(marker="s", color=pal.BLUE_DARK, face=pal.BLUE_LIGHT, label="GR"),
        "ER": dict(marker="D", color=pal.BLUE, face=pal.BLUE, label="ER"),
    }
    for yy, row in zip(y, rows):
        points = [100 * row["rates"][policy][0] for policy in ("NR", "GR", "ER")]
        ax_rate.plot([min(points), max(points)], [yy, yy],
                     color=pal.GRAY, lw=1.0, zorder=1)
        for policy, point in zip(("NR", "GR", "ER"), points):
            spec = style[policy]
            rate = row["rates"][policy]
            if rate[1] is not None:
                xerr = [[point - 100 * rate[1]], [100 * rate[2] - point]]
            else:
                xerr = None
            ax_rate.errorbar(point, yy, xerr=xerr, fmt=spec["marker"],
                             color=spec["color"], ecolor=spec["color"],
                             markerfacecolor=spec["face"], markeredgecolor=spec["color"],
                             markeredgewidth=0.8, elinewidth=0.8, capsize=2,
                             markersize=4.2, zorder=3)
        mean, lo, hi = [100 * value for value in row["effect"]]
        col = pal.BLUE_DARK if row["model"] == "__pooled__" else pal.BLUE
        ax_effect.errorbar(mean, yy, xerr=[[mean - lo], [hi - mean]], fmt="D",
                           color=col, ecolor=col, markerfacecolor=col,
                           markeredgecolor="white", markeredgewidth=0.4,
                           elinewidth=1.2, capsize=2.2, markersize=4.1, zorder=3)
        ax_effect.text(87, yy, f"{mean:+.1f}", ha="right", va="center",
                       fontsize=6.2, fontweight="bold", color="#1A1A1A")
    labels = [f"{SHORT[row['model']]} ({row['scenarios']})" if row["model"] != "__pooled__"
              else "Pooled (14)" for row in rows]
    ax_rate.set_yticks(y); ax_rate.set_yticklabels(labels, fontsize=6.4)
    ax_rate.get_yticklabels()[-1].set_fontweight("bold")
    ax_rate.set_xlim(15, 102)
    ax_rate.set_xticks([20, 40, 60, 80, 100])
    ax_rate.set_xlabel("Patch application (%)", fontsize=6.8)
    ax_rate.grid(axis="x", color="#EAF1F6", lw=0.8)
    for policy, spec in style.items():
        ax_rate.plot([], [], marker=spec["marker"], linestyle="none",
                     markerfacecolor=spec["face"], markeredgecolor=spec["color"],
                     label=spec["label"], markersize=4)
    ax_rate.legend(loc="lower center", bbox_to_anchor=(0.52, 1.00), fontsize=6.7,
                   ncol=3, handlelength=0.7, columnspacing=0.7)
    ax_effect.axvline(0, color="#333333", lw=0.9, ls=":")
    ax_effect.set_xlim(-45, 90); ax_effect.set_xticks([-40, 0, 40])
    ax_effect.set_xlabel("ER \u2212 GR\n(percentage points)", fontsize=6.7)
    ax_effect.grid(axis="x", color="#EAF1F6", lw=0.8)
    ax_rate.invert_yaxis()
    for ax in (ax_rate, ax_effect):
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(axis="x", labelsize=6.4)
        ax.tick_params(axis="y", length=0)
    fig.subplots_adjust(left=0.30, right=0.99, bottom=0.19, top=0.88)
    _save(fig, "fig_apply_lift")


def fig_funnel(data):
    panel = matched_retry_panel(data)
    thresholds = [0.0, 0.01, 0.05, 0.10]
    results = [scenario_balanced_outcomes(panel, threshold=value) for value in thresholds]
    at_five = results[2]
    segs = [
        ("not applied", "not_applied", pal.RAMP4[0]),
        ("failed tests", "broke_tests", pal.RAMP4[1]),
        ("tests pass, \u22645% gain", "pass_other", pal.RAMP4[2]),
        ("tests pass, >5% gain", "pass_faster", pal.RAMP4[3]),
    ]
    fig, (ax_bar, ax_curve) = plt.subplots(
        2, 1, figsize=(3.5, 2.95), gridspec_kw={"height_ratios": [1.0, 1.05], "hspace": 0.78}
    )
    policies = ["NR", "GR", "ER"]
    y = list(range(3)); left = [0.0] * 3
    for label, key, color in segs:
        vals = [100 * at_five["levels"][policy][key] for policy in policies]
        ax_bar.barh(y, vals, 0.55, left=left, label=label, color=color,
                    edgecolor="white", linewidth=0.45)
        for i, (start, value) in enumerate(zip(left, vals)):
            if value >= 8:
                txt = "white" if key in ("not_applied", "pass_faster") else "#1a1a1a"
                ax_bar.text(start + value / 2, i, f"{value:.0f}%", ha="center", va="center",
                            fontsize=6.1, fontweight="bold", color=txt)
        left = [start + value for start, value in zip(left, vals)]
    ax_bar.set_yticks(y); ax_bar.set_yticklabels(policies, fontsize=6.5)
    ax_bar.set_xlim(0, 100); ax_bar.invert_yaxis()
    ax_bar.set_xlabel("Share of rounds (%)\n(equal weight per scenario)", fontsize=6.5)
    ax_bar.legend(loc="lower center", bbox_to_anchor=(0.52, 1.18), fontsize=6.2,
                  ncol=2, handlelength=1.0, columnspacing=0.8)
    ax_bar.text(0.0, 1.11, "a", transform=ax_bar.transAxes,
                fontsize=8, fontweight="bold")

    x = [0, 1, 5, 10]
    policy_style = {
        "NR": (pal.GRAY_DARK, "o", "white"),
        "GR": (pal.BLUE_DARK, "s", pal.BLUE_LIGHT),
        "ER": (pal.BLUE, "D", pal.BLUE),
    }
    for policy in policies:
        means = [100 * result["level_intervals"][("pass_faster", policy)][0] for result in results]
        lows = [100 * result["level_intervals"][("pass_faster", policy)][1] for result in results]
        highs = [100 * result["level_intervals"][("pass_faster", policy)][2] for result in results]
        color, marker, face = policy_style[policy]
        ax_curve.errorbar(x, means,
                          yerr=[[m - lo for m, lo in zip(means, lows)],
                                [hi - m for m, hi in zip(means, highs)]],
                          label=policy, color=color, marker=marker, markerfacecolor=face,
                          markeredgecolor=color, markeredgewidth=0.7, lw=1.2,
                          elinewidth=0.7, capsize=2, markersize=3.8)
    ax_curve.set_xticks(x); ax_curve.set_xticklabels(["0", "1", "5", "10"])
    ax_curve.set_xlabel("Required recorded speedup (%)", fontsize=6.8)
    ax_curve.set_ylabel("Test-passing rounds\nabove cutoff (%)", fontsize=6.8)
    ax_curve.set_ylim(0, 40); ax_curve.grid(axis="y", color="#EAF1F6", lw=0.8)
    ax_curve.legend(loc="upper right", fontsize=6.3, ncol=3, columnspacing=0.7,
                    handlelength=1.0)
    ax_curve.text(0.0, 1.05, "b", transform=ax_curve.transAxes,
                  fontsize=8, fontweight="bold")
    for ax in (ax_bar, ax_curve):
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(axis="both", labelsize=6.3)
    fig.subplots_adjust(left=0.18, right=0.98, bottom=0.12, top=0.86)
    _save(fig, "fig_funnel")


def fig_retry_shift(data):
    """Show three consistently signed contrasts with scenario uncertainty."""
    panel = matched_retry_panel(data)
    rows = model_outcome_effects(panel, threshold=0.05)
    pooled = next(row for row in rows if row["model"] == "__pooled__")
    rows = sorted(
        (row for row in rows if row["model"] != "__pooled__"),
        key=lambda row: row["effects"]["applied"][0], reverse=True,
    ) + [pooled]
    keys = ["applied", "broke_tests", "pass_faster"]
    labels = [
        (f"{SHORT[row['model']]} ({row['scenarios']})"
         if row["model"] != "__pooled__" else "Pooled (14)")
        for row in rows
    ]

    y = list(range(len(rows) - 1)) + [len(rows) - 0.35]
    fig, axes = plt.subplots(1, 3, figsize=(3.5, 2.12), sharey=True,
                             gridspec_kw={"wspace": 0.18})
    limit = 10 * math.ceil(max(abs(100 * bound) for row in rows for key in keys
                              for bound in row["effects"][key][1:]) / 10)
    tick = 20 if limit < 40 else 40
    for ax, key, title in zip(axes, keys, ["Applied\npatch", "Failed\ntests", "Passing gain\n>5%"]):
        _stripe_rows(ax, y[:-1])
        ax.axhspan(y[-1] - 0.48, y[-1] + 0.48, color="#EAF1F6", zorder=0)
        ax.axvline(0, color=pal.GRAY_DARK, lw=0.8, ls=":", zorder=1)
        for yy, row in zip(y, rows):
            mean, lo, hi = [100 * value for value in row["effects"][key]]
            is_pooled = row["model"] == "__pooled__"
            color = pal.BLUE_DARK if is_pooled else pal.BLUE
            ax.errorbar(mean, yy, xerr=[[mean - lo], [hi - mean]],
                        fmt="D" if is_pooled else "o", color=color, ecolor=color,
                        markerfacecolor=color if is_pooled else "white",
                        markersize=4.0, markeredgewidth=0.8, elinewidth=1.0,
                        capsize=2.0, zorder=3)
        ax.set_xlim(-limit, limit)
        ax.set_xticks([-tick, 0, tick])
        ax.set_xticklabels([f"-{tick}", "0", f"+{tick}"])
        ax.set_title(title, fontsize=6.7, pad=6)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(axis="x", labelsize=6.1, length=2.5)
        ax.tick_params(axis="y", length=0)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels(labels, fontsize=6.3)
    axes[0].get_yticklabels()[-1].set_fontweight("bold")
    axes[0].invert_yaxis()
    fig.text(0.64, 0.025, "ER \u2212 GR (percentage points)", ha="center", fontsize=6.8)
    fig.subplots_adjust(left=0.30, right=0.99, bottom=0.17, top=0.85)
    _save(fig, "fig_retry_shift")


def fig_fidelity(data):
    rows = tidy(data)
    if not rows:
        print("  [fidelity] no complete OFF cell yet"); return
    results = f3_common_panel_results(rows)
    contrast_rows = results["contrasts"]
    labels = [
        "directional", "numbers", "benchstat", "fresh CPU profile", "line allocation profile",
        "baseline profile", "baseline vs.\nfresh CPU profile",
    ]
    colors = [pal.BLUE] * 5 + [pal.GRAY_DARK] * 2
    y = [7, 6, 5, 4, 3, 2, 0.5]
    fig, ax_forest = plt.subplots(figsize=(3.5, 2.10))
    _stripe_rows(ax_forest, y[:6])
    ax_forest.axhline(1.15, color=pal.GRAY, linewidth=0.6)
    family_bounds = [bound for r in contrast_rows for bound in r["ci_familywise"]]
    xmin, xmax = min(family_bounds), max(family_bounds)
    pad = max(0.02, 0.08 * (xmax - xmin))
    right = xmax + 0.055
    label_x = right - 0.004
    for i, (yy, label, col, r) in enumerate(zip(y, labels, colors, contrast_rows)):
        lo, hi = r["ci"]
        family_lo, family_hi = r["ci_familywise"]
        mean = r["mean"]
        ax_forest.plot([family_lo, family_hi], [yy, yy], color=pal.GRAY_DARK,
                       linewidth=0.9, alpha=0.85, zorder=1)
        ax_forest.vlines([family_lo, family_hi], yy - 0.065, yy + 0.065,
                         color=pal.GRAY_DARK, linewidth=0.8, alpha=0.85, zorder=1)
        is_baseline = i >= len(contrast_rows) - 2
        marker = "s" if is_baseline else "D"
        face = "white" if i == len(contrast_rows) - 1 else col
        ax_forest.errorbar(
            mean,
            yy,
            xerr=[[mean - lo], [hi - mean]],
            fmt=marker,
            color=col,
            ecolor=col,
            markerfacecolor=face,
            markeredgecolor=col,
            markeredgewidth=0.8,
            elinewidth=2.0,
            capsize=3,
            markersize=4.3,
            zorder=3,
        )
        ax_forest.text(label_x, yy, f"{mean:+.3f}", ha="right", va="center",
                       fontsize=6.4, fontweight="bold", color="#1A1A1A")
    ax_forest.axvline(0, color="#333333", lw=1, ls=":")
    ax_forest.set_yticks(y)
    ax_forest.set_yticklabels(labels)
    ax_forest.set_xlim(xmin - pad, right)
    ax_forest.set_xlabel("Paired mean score difference", fontsize=7.3)
    ax_forest.text(-0.03, 1.04, "Policy vs. none", transform=ax_forest.transAxes,
                   ha="right", va="bottom", fontsize=6.7, fontweight="bold")
    ax_forest.text(0.995, 1.02, "Mean", transform=ax_forest.transAxes,
                   ha="right", va="bottom", fontsize=6.5, color="#1A1A1A")
    ax_forest.grid(axis="x", color="#EAF1F6", lw=0.8)
    ax_forest.spines[["top", "right", "left"]].set_visible(False)
    ax_forest.tick_params(axis="x", labelsize=7)
    ax_forest.tick_params(axis="y", labelsize=6.8)
    ax_forest.tick_params(axis="y", length=0)
    ax_forest.set_ylim(-0.35, 7.55)
    fig.subplots_adjust(left=0.36, right=0.99, bottom=0.19, top=0.88)
    _save(fig, "fig_fidelity")


def main():
    data = build_data(verbose=False)
    print(f"[figs] -> {', '.join(FIGDIRS)}")
    fig_apply_lift(data); fig_funnel(data)
    fig_retry_shift(data); fig_fidelity(data)


if __name__ == "__main__":
    main()
