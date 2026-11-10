#!/usr/bin/env python3
"""Composition, seed, threshold, and gold-range sensitivities for F3."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from analyze_fleet import FIXED_GOLD, build_data  # noqa: E402
from fid_data import best_per_cell, tidy  # noqa: E402
from fid_rigor import (  # noqa: E402
    B, CONTRAST_SPECS, _contrast_result, f3_common_panel_results,
    f3_contrast_results,
)

ARMS = ("none", "directional", "numbers", "benchstat", "prof_cpu", "prof_line", "misleading")


def _map_without_seed(rows, arm):
    values = best_per_cell(rows, lambda row: row["arm"] == arm)
    return {(model, scenario): value for (model, scenario, _), value in values.items()}


def seed_sensitivity(data=None, b=B):
    """Compare the two complete registry-labeled SEED1 models with their OFF rows."""
    data = data if data is not None else build_data(verbose=False)
    seed0, seed1 = tidy(data, conditions=("OFF",)), tidy(data, conditions=("SEED1",))
    seed1_scenarios = {}
    for row in seed1:
        seed1_scenarios.setdefault(row["model"], set()).add(row["scenario"])
    complete_models = {model for model, scenarios in seed1_scenarios.items() if len(scenarios) == 14}
    seed0 = [row for row in seed0 if row["model"] in complete_models]
    seed1 = [row for row in seed1 if row["model"] in complete_models]
    maps0 = {arm: _map_without_seed(seed0, arm) for arm in ARMS}
    maps1 = {arm: _map_without_seed(seed1, arm) for arm in ARMS}
    keys = sorted(set.intersection(*(set(values) for values in (*maps0.values(), *maps1.values()))))
    results = []
    for name, arm_a, arm_b, _ in CONTRAST_SPECS:
        pairs0 = [(maps0[arm_a][key], maps0[arm_b][key], key[0], key[1]) for key in keys]
        pairs1 = [(maps1[arm_a][key], maps1[arm_b][key], key[0], key[1]) for key in keys]
        deltas = [
            (maps1[arm_a][key] - maps1[arm_b][key],
             maps0[arm_a][key] - maps0[arm_b][key], key[0], key[1])
            for key in keys
        ]
        results.append(dict(
            name=name,
            seed0=_contrast_result(name, pairs0, b=b, seed_key=f"seed0:{name}"),
            seed1=_contrast_result(name, pairs1, b=b, seed_key=f"seed1:{name}"),
            delta=_contrast_result(name, deltas, b=b, seed_key=f"seed-delta:{name}"),
        ))
    return dict(n=len(keys), models=len({key[0] for key in keys}), results=results)


def composition_sensitivity(data=None, b=B):
    data = data if data is not None else build_data(verbose=False)
    rows = tidy(data)
    low_gold_removed = {scenario for scenario, gold in FIXED_GOLD.items() if gold >= 1.5}
    outlier_removed = {scenario for scenario, gold in FIXED_GOLD.items() if gold < 1000}
    return dict(
        common=f3_common_panel_results(rows, b=b),
        low_gold=f3_contrast_results([row for row in rows if row["scenario"] in low_gold_removed], b=b),
        outlier=f3_contrast_results([row for row in rows if row["scenario"] in outlier_removed], b=b),
    )


def threshold_sensitivity(data=None, b=B):
    data = data if data is not None else build_data(verbose=False)
    return {
        threshold: f3_contrast_results(
            tidy(data, minimum_speedup=1.0 + threshold), b=b
        )
        for threshold in (0.01, 0.05, 0.10)
    }


def _line(result):
    lo, hi = result["ci"]
    flo, fhi = result["ci_familywise"]
    return (f"{result['name']:28s} n={result['n']:3d} mean={result['mean']:+.4f} "
            f"CI=[{lo:+.4f},{hi:+.4f}] FWER=[{flo:+.4f},{fhi:+.4f}]")


def main():
    b = int(os.environ.get("ACBENCH_BOOTSTRAPS", B))
    data = build_data(verbose=False)
    composition = composition_sensitivity(data, b=b)
    common = composition["common"]
    print(f"=== Common seven-policy panel: n={common['n']}, models={common['models']} ===")
    for result in common["contrasts"]:
        print(_line(result))
    seeds = seed_sensitivity(data, b=b)
    print(f"\n=== Archived two-model seed sensitivity: n={seeds['n']}, models={seeds['models']} ===")
    for row in seeds["results"]:
        print(row["name"])
        print("  seed0", _line(row["seed0"]))
        print("  seed1", _line(row["seed1"]))
        print("  delta", _line(row["delta"]))
    for label in ("low_gold", "outlier"):
        print(f"\n=== Composition sensitivity: {label} ===")
        for result in composition[label]["contrasts"]:
            print(_line(result))
    for threshold, results in threshold_sensitivity(data, b=b).items():
        print(f"\n=== Minimum recorded speedup: {threshold:.0%} ===")
        for result in results["contrasts"]:
            print(_line(result))


if __name__ == "__main__":
    main()
