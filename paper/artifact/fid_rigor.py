#!/usr/bin/env python3
"""Code-regenerable fixed-gold statistics for the paper.

F1: descriptive per-model apply-rate Wilson 95% CIs plus the k/N sign test.
F3: five separate candidate-derived-arm-versus-none contrasts plus
baseline-profile-versus-prof_cpu,
with scenario-cluster bootstrap CIs, familywise Bonferroni intervals, non-tied
pair counts, an 80%-power cluster-bootstrap MDE, and exposure accounting.

Scores come from :mod:`fid_data`, which recomputes them from recorded rounded
speedups, correctness, and fixed manifest gold.  The max-over-five selector is
reported only as a descriptive opportunity-bias diagnostic, never as positive
evidence.

Run: python3 paper/fid_rigor.py   (deterministic; seed fixed)
"""
from __future__ import annotations

import math
import os
import random
import sys
import zlib
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_fleet import (  # noqa: E402
    SCORING_NOTE,
    VALIDATED_MANIFEST,
    build_data,
)
from fid_data import SEL, best_per_cell, paired_by_scenario, tidy  # noqa: E402

B = 100000
SEED = 20260705
FAITHFUL_ARMS = ("directional", "numbers", "benchstat", "prof_cpu", "prof_line")
CONTRAST_SPECS = (
    ("directional vs none", "directional", "none", "directional vs none"),
    ("numbers vs none", "numbers", "none", "numbers vs none"),
    ("benchstat vs none", "benchstat", "none", "benchstat vs none"),
    ("prof_cpu vs none", "prof_cpu", "none", "prof_cpu vs none"),
    ("prof_line vs none", "prof_line", "none", "prof_line vs none"),
    ("base_prof vs none", "misleading", "none", "base_prof vs none"),
    # Keep the historical bootstrap stream while using an accurate display label.
    ("base_prof vs prof_cpu", "misleading", "prof_cpu", "stale vs prof_cpu"),
)
FAMILY_ALPHA = 0.05


def wilson(k, n, z=1.959963985):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    half = (z / d) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (p, max(0.0, c - half), min(1.0, c + half))


def apply_rate_rows(data=None):
    """Return per-model OFF/ON apply-rate rows for F1."""
    data = data if data is not None else build_data(verbose=False)
    ac = {}
    for (m, c), rows in data.items():
        if c not in ("OFF", "ON"):
            continue
        n = len(rows)
        k = sum(1 for x in rows if str(x.get("applied")).lower() == "true")
        ac[(m, c)] = (k, n)
    both = sorted({m for (m, c) in ac if c == "OFF"} & {m for (m, c) in ac if c == "ON"})
    out = []
    for m in both:
        ko, no = ac[(m, "OFF")]
        kn, nn = ac[(m, "ON")]
        po, lo, uo = wilson(ko, no)
        pn, ln, un = wilson(kn, nn)
        out.append(dict(
            model=m,
            off=(po, lo, uo, no),
            on=(pn, ln, un, nn),
            lift=pn - po,
        ))
    return out


def _arm_selector(arm):
    return lambda row: row["arm"] == arm


def _quantile(sorted_values, probability):
    """Linearly interpolated empirical quantile for a sorted bootstrap sample."""
    if not sorted_values:
        return 0.0
    position = max(0.0, min(1.0, probability)) * (len(sorted_values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _contrast_result(name, pairs, b=B, family_size=len(CONTRAST_SPECS), seed=SEED,
                     seed_key=None):
    """Scenario-cluster contrast with raw and familywise-adjusted intervals."""
    diffs = [a - b0 for (a, b0, _, _) in pairs]
    n = len(diffs)
    mean = sum(diffs) / n if n else 0.0
    nz = [d for d in diffs if abs(d) > 1e-9]
    sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (n - 1)) if n > 1 else 0.0
    by = defaultdict(list)
    for (a, b0, _, sc) in pairs:
        by[sc].append(a - b0)
    scens = list(by)
    boots = []
    # Make each contrast reproducible and invariant to reporting order.
    rng = random.Random(seed + zlib.crc32((seed_key or name).encode("utf-8")))
    if scens:
        for _ in range(b):
            samp = [rng.choice(scens) for _ in scens]
            vals = [d for s in samp for d in by[s]]
            boots.append(sum(vals) / len(vals))
    boot_mean = sum(boots) / len(boots) if boots else 0.0
    boot_se = (
        math.sqrt(sum((x - boot_mean) ** 2 for x in boots) / (len(boots) - 1))
        if len(boots) > 1 else 0.0
    )
    boots.sort()
    lo = _quantile(boots, 0.025)
    hi = _quantile(boots, 0.975)
    adjusted_alpha = FAMILY_ALPHA / family_size
    family_lo = _quantile(boots, adjusted_alpha / 2)
    family_hi = _quantile(boots, 1 - adjusted_alpha / 2)
    mde = 2.801 * boot_se if n else 0.0
    posn = sum(1 for d in nz if d > 0)
    return dict(
        name=name,
        pairs=pairs,
        n=n,
        clusters=len(scens),
        non_tied=len(nz),
        mean=mean,
        ci=(lo, hi),
        ci_familywise=(family_lo, family_hi),
        family_individual_level=1 - adjusted_alpha,
        sd=sd,
        mde=mde,
        sign=(posn, len(nz)),
    )


def f3_contrast_results(rows=None, b=B, seed=SEED):
    """Return seven order-invariant F3 contrasts and selector-bias diagnostics."""
    rows = rows if rows is not None else tidy()
    contrasts = []
    for name, arm_a, arm_b, seed_key in CONTRAST_SPECS:
        contrasts.append(_contrast_result(
            name,
            paired_by_scenario(rows, _arm_selector(arm_a), _arm_selector(arm_b)),
            b=b,
            seed=seed,
            seed_key=seed_key,
        ))

    maps = {
        arm: best_per_cell(rows, _arm_selector(arm))
        for arm in ("none",) + FAITHFUL_ARMS
    }
    complete_keys = sorted(set.intersection(*(set(values) for values in maps.values())))
    observed = []
    random_singleton = []
    all_arms = ("none",) + FAITHFUL_ARMS
    for key in complete_keys:
        values = {arm: maps[arm][key] for arm in all_arms}
        observed.append(max(values[arm] for arm in FAITHFUL_ARMS) - values["none"])
        random_singleton.append(sum(
            max(values[other] for other in all_arms if other != singled) - values[singled]
            for singled in all_arms
        ) / len(all_arms))
    observed_mean = sum(observed) / len(observed) if observed else 0.0
    opportunity_mean = sum(random_singleton) / len(random_singleton) if random_singleton else 0.0
    return dict(
        contrasts=contrasts,
        family_size=len(CONTRAST_SPECS),
        family_alpha=FAMILY_ALPHA,
        family_individual_level=1 - FAMILY_ALPHA / len(CONTRAST_SPECS),
        selector_bias=dict(
            n=len(complete_keys),
            observed=observed_mean,
            opportunity=opportunity_mean,
            excess=observed_mean - opportunity_mean,
        ),
    )


def f3_common_panel_results(rows=None, b=B, seed=SEED):
    """Seven contrasts on one fixed set of cells containing every policy.

    This removes changing model/cell composition across contrasts.  It is the
    preferred policy-comparison panel; available-pair results remain a sensitivity
    that uses more data for individual contrasts.
    """
    rows = rows if rows is not None else tidy()
    arms = ("none",) + FAITHFUL_ARMS + ("misleading",)
    maps = {arm: best_per_cell(rows, _arm_selector(arm)) for arm in arms}
    complete_keys = sorted(set.intersection(*(set(values) for values in maps.values())))
    contrasts = []
    for name, arm_a, arm_b, _ in CONTRAST_SPECS:
        pairs = [(maps[arm_a][key], maps[arm_b][key], key[0], key[1])
                 for key in complete_keys]
        contrasts.append(_contrast_result(
            name, pairs, b=b, family_size=len(CONTRAST_SPECS), seed=seed,
            seed_key=f"common-seven:{arm_a}:{arm_b}",
        ))
    return dict(
        contrasts=contrasts,
        n=len(complete_keys),
        models=len({key[0] for key in complete_keys}),
        clusters=len({key[1] for key in complete_keys}),
        keys=complete_keys,
    )


def f3_pooled_arm_means(rows=None):
    """Pooled unpaired means for the three headline single-arm conditions."""
    rows = rows if rows is not None else tidy()
    arms = [
        ("none", SEL["none"]),
        ("fresh prof_cpu", SEL["faithful"]),
        ("baseline profile", SEL["misleading"]),
    ]
    out = []
    for label, sel in arms:
        vals = list(best_per_cell(rows, sel).values())
        out.append(dict(label=label, mean=sum(vals) / len(vals) if vals else 0.0, n=len(vals)))
    return out


def profile_exposure(rows):
    """Count slots/cells where a measured candidate could feed the next prompt."""
    by_cell = defaultdict(list)
    for r in rows:
        by_cell[(r["model"], r["scenario"], r["seed"], r["arm"])].append(r)
    out = defaultdict(lambda: dict(events=0, opportunities=0, cells_with=0, cells=0))
    for (_, _, _, arm), cell_rows in by_cell.items():
        max_it = max(r["it"] for r in cell_rows)
        prefinal = [r for r in cell_rows if r["it"] < max_it]
        events = sum(
            1 for r in prefinal
            if r["correct"] and r.get("measured_speedup") is not None
            and r["measured_speedup"] > 0
        )
        out[arm]["events"] += events
        out[arm]["opportunities"] += len(prefinal)
        out[arm]["cells_with"] += int(events > 0)
        out[arm]["cells"] += 1
    return out


def print_apply_rate_report(data=None):
    rows = apply_rate_rows(data)
    print("=== Raw unmatched OFF -> ON diagnostic (not manuscript F1; Wilson 95% CI) ===")
    for r in rows:
        po, lo, uo, no = r["off"]
        pn, ln, un, nn = r["on"]
        print(
            f"  {r['model']:17s} OFF {po*100:3.0f}% [{lo*100:2.0f},{uo*100:3.0f}] n={no:3d} | "
            f"ON {pn*100:3.0f}% [{ln*100:2.0f},{un*100:3.0f}] n={nn:3d} | "
            f"lift {r['lift']*100:+.0f}pp"
        )
    pos = sum(1 for r in rows if r["lift"] > 0)
    n = len(rows)
    print(
        f"  SIGN TEST across models: {pos}/{n} positive  ->  exact one-sided p = {0.5**n:.4f} "
        f"(two-sided {2 * 0.5**n if pos == n else float('nan'):.4f})"
    )


def print_contrast(r):
    lo, hi = r["ci"]
    family_lo, family_hi = r["ci_familywise"]
    posn, signn = r["sign"]
    print(f"  {r['name']}")
    print(
        f"     n={r['n']} pairs ({r['clusters']} scenario clusters), non-tied={r['non_tied']} | "
        f"mean {r['mean']:+.3f} | unadjusted scenario-cluster 95% CI [{lo:+.3f}, {hi:+.3f}] | "
        f"SD {r['sd']:.3f} | cluster-MDE(80%) ~{r['mde']:.3f} | sign {posn}/{signn}"
    )
    print(
        f"     Bonferroni familywise interval "
        f"({100*r['family_individual_level']:.2f}% individual): "
        f"[{family_lo:+.3f}, {family_hi:+.3f}]"
    )


def print_exposure(rows):
    exp = profile_exposure(rows)

    def line(label, arms):
        events = sum(exp[a]["events"] for a in arms)
        opps = sum(exp[a]["opportunities"] for a in arms)
        cells_with = sum(exp[a]["cells_with"] for a in arms)
        cells = sum(exp[a]["cells"] for a in arms)
        er = 100 * events / opps if opps else 0.0
        cr = 100 * cells_with / cells if cells else 0.0
        print(
            f"  {label:18s} exposure events {events:3d}/{opps:4d} ({er:4.1f}%) | "
            f"arm-cells with exposure {cells_with:3d}/{cells:3d} ({cr:4.1f}%)"
        )

    print("\n=== Profile-exposure accounting in OFF fidelity cells ===")
    print(
        "  Exposure event = correct measured candidate in a pre-final slot, "
        "so a later prompt can receive the payload."
    )
    line("prof_cpu", ("prof_cpu",))
    line("baseline profile", ("misleading",))
    line("faithful arms", FAITHFUL_ARMS)


def main():
    data = build_data(verbose=False)
    print(f"SCORING: {SCORING_NOTE}")
    print(f"FIXED GOLD: {VALIDATED_MANIFEST.parent.name}/{VALIDATED_MANIFEST.name}")
    print_apply_rate_report(data)
    rows = tidy(data)
    seeds = sorted({str(r["seed"]) for r in rows})
    print("\n=== Fixed-gold pooled unpaired means (descriptive) ===")
    for arm in f3_pooled_arm_means(rows):
        print(f"  {arm['label']:16s} mean={arm['mean']:.3f} n={arm['n']}")
    print(f"\n=== F3 fixed-gold arm-by-arm paired contrasts (B={B}) ===")
    print(
        "  INFERENCE SCOPE: scenario-cluster uncertainty conditional on the measured model panel "
        f"and decoding seed(s) {seeds}; generation-seed variance is not estimated."
    )
    results = f3_contrast_results(rows)
    print(
        f"  MULTIPLICITY: {results['family_size']} reported contrasts; raw 95% CIs are unadjusted. "
        f"Bonferroni {100*results['family_individual_level']:.2f}% individual intervals provide "
        "95% familywise coverage across this family."
    )
    for r in results["contrasts"]:
        print_contrast(r)
    common = f3_common_panel_results(rows)
    print(
        f"\n=== F3 common seven-policy panel: n={common['n']} cells, "
        f"{common['models']} models, {common['clusters']} scenarios ==="
    )
    for r in common["contrasts"]:
        print_contrast(r)
    selector = results["selector_bias"]
    print("\n=== Descriptive max-over-five selector-bias diagnostic (NOT positive evidence) ===")
    print(f"  complete six-arm cells: n={selector['n']}")
    print(f"  observed max(five faithful)-none: {selector['observed']:+.3f}")
    print(f"  random-singleton five-vs-one opportunity baseline: {selector['opportunity']:+.3f}")
    print(f"  observed minus opportunity baseline: {selector['excess']:+.3f}")
    print("  No inferential CI is reported; this outcome-selected statistic is excluded from the contrast family.")
    print_exposure(rows)


if __name__ == "__main__":
    main()
