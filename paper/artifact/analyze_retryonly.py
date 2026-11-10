#!/usr/bin/env python3
"""Retry-only control for F1.

The retry-only jobs are registered as rc-* shards. This script merges all rc-*
shards per model, deduplicates rows, and compares OFF / RETRY-ONLY / ON on the
same scenario subset for each model. Content effects are reported as
scenario-cluster bootstrap CIs over ON minus RETRY-ONLY scenario-level apply
rates; no independent-attempt p-values are used.

Run: python3 paper/analyze_retryonly.py
"""
from __future__ import annotations

import math
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from analyze_fleet import build_data  # noqa: E402

B = 5000
RNG = random.Random(20260709)


def _is_applied(row) -> bool:
    return str(row.get("applied")).lower() == "true"


def rate(rows):
    n = len(rows)
    k = sum(1 for x in rows if _is_applied(x))
    return k, n, (k / n if n else 0.0)


def wilson(k, n, z=1.96):
    if not n:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = (z / d) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, c - h), min(1.0, c + h)


def merge_rows(groups):
    """Deduplicate rows from multiple rc-* shards.

    Shards are intended to be disjoint by scenario, but this guard prevents stale
    re-runs from double-counting the same candidate.
    """
    out, seen = [], set()
    for rows in groups:
        for x in rows:
            key = (x.get("scenario_id"), x.get("arm"), x.get("seed"), x.get("iteration"))
            if key in seen:
                continue
            seen.add(key)
            out.append(x)
    return out


def filter_scenarios(rows, scenarios):
    return [x for x in rows if x.get("scenario_id") in scenarios]


def scenario_apply_rates(rows):
    by_scenario = defaultdict(list)
    for x in rows:
        by_scenario[x["scenario_id"]].append(x)
    return {sc: rate(rs)[2] for sc, rs in by_scenario.items()}


def cluster_ci(diff_by_scenario, b=B):
    """Bootstrap the mean scenario-level difference by resampling scenarios."""
    vals = list(diff_by_scenario.values())
    if not vals:
        return 0.0, 0.0, 0.0
    mean = sum(vals) / len(vals)
    boots = []
    for _ in range(b):
        samp = [RNG.choice(vals) for _ in vals]
        boots.append(sum(samp) / len(samp))
    boots.sort()
    return mean, boots[int(0.025 * b)], boots[int(0.975 * b)]


def pct(x):
    return f"{x * 100:.0f}%"


def pp(x):
    return f"{x * 100:+.1f}pp"


def main():
    data = build_data(verbose=False)
    rc_conds = sorted({c for (_, c) in data if str(c).lower().startswith("rc")})
    print(f"retry-only conds found: {rc_conds or '(none)'}")

    models = sorted({m for (m, c) in data if c == "OFF"} & {m for (m, c) in data if c == "ON"})
    rows_for_table = []
    pooled_by_scenario = defaultdict(list)

    print("\n=== F1 CONTROL: OFF vs RETRY-ONLY vs ON on matched scenario subsets ===")
    print(f"{'model':17s} {'scen':>4s} {'OFF':>18s} {'RETRY-ONLY':>18s} {'ON':>18s} {'ON-rc cluster CI':>25s}")
    for m in models:
        rc_groups = [data[(m, c)] for c in rc_conds if (m, c) in data]
        if not rc_groups:
            continue
        rc_rows = merge_rows(rc_groups)
        scenarios = sorted({x["scenario_id"] for x in rc_rows})
        off_rows = filter_scenarios(data[(m, "OFF")], scenarios)
        on_rows = filter_scenarios(data[(m, "ON")], scenarios)

        ko, no, po = rate(off_rows)
        kr, nr, pr = rate(rc_rows)
        kn, nn, pn = rate(on_rows)
        lo_o, hi_o = wilson(ko, no)
        lo_r, hi_r = wilson(kr, nr)
        lo_n, hi_n = wilson(kn, nn)

        rc_s = scenario_apply_rates(rc_rows)
        on_s = scenario_apply_rates(on_rows)
        diff_s = {sc: on_s[sc] - rc_s[sc] for sc in sorted(set(rc_s) & set(on_s))}
        d, lo, hi = cluster_ci(diff_s)
        for sc, val in diff_s.items():
            pooled_by_scenario[sc].append(val)

        rows_for_table.append(dict(
            model=m, scenarios=len(scenarios), off=(ko, no, po), rc=(kr, nr, pr),
            on=(kn, nn, pn), diff=d, ci=(lo, hi)))

        print(f"{m:17s} {len(scenarios):4d} "
              f"{pct(po):>4s} [{pct(lo_o):>3s},{pct(hi_o):>4s}] "
              f"{pct(pr):>4s} [{pct(lo_r):>3s},{pct(hi_r):>4s}] "
              f"{pct(pn):>4s} [{pct(lo_n):>3s},{pct(hi_n):>4s}] "
              f"{pp(d):>8s} [{pp(lo):>8s},{pp(hi):>8s}]")

    print("\n=== TABLE ROWS (rates rounded for LaTeX) ===")
    print(f"{'model':17s} {'scen':>4s} {'slots':>17s} {'OFF':>5s} {'RC':>5s} {'ON':>5s} {'ON-RC CI':>23s}")
    for r in rows_for_table:
        ko, no, po = r["off"]
        kr, nr, pr = r["rc"]
        kn, nn, pn = r["on"]
        lo, hi = r["ci"]
        slots = f"{no}/{nr}/{nn}"
        print(f"{r['model']:17s} {r['scenarios']:4d} {slots:>17s} "
              f"{pct(po):>5s} {pct(pr):>5s} {pct(pn):>5s} "
              f"[{pp(lo):>8s},{pp(hi):>8s}]")

    if pooled_by_scenario:
        pooled = {sc: sum(v) / len(v) for sc, v in pooled_by_scenario.items()}
        d, lo, hi = cluster_ci(pooled)
        print("\n=== POOLED CONTENT EFFECT (scenario-cluster mean of model-level ON-RC differences) ===")
        print(f"ON minus RETRY-ONLY = {pp(d)} with scenario-cluster 95% CI [{pp(lo)}, {pp(hi)}]")

    print("\nInterpretation: retry-only is computed on the same scenario subset as OFF and ON for each model.")
    print("A cluster CI spanning zero means the error text adds no clear lift beyond the extra attempts.")


if __name__ == "__main__":
    main()
