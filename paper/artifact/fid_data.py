#!/usr/bin/env python3
"""Shared tidy data layer for fidelity-comparison figures (none / faithful / misleading / adversarial).

Single loader so every figure script uses identical data. Sourced from
``analyze_fleet.build_data()`` (the canonical registry-driven, dedup'd loader).
OFF arms by default (apply-feedback off = the fidelity axis), with an explicit
condition selector for archived seed-sensitivity audits. Scores and running bests
are recomputed from recorded three-decimal speedups, correctness, and the fixed
validated-manifest gold; stored score columns are never read.

Usage:
    from fid_data import tidy, off_models, ARM_ORDER, ARM_COLOR, classify
    rows = tidy()                      # list of dicts (one per scenario,arm,seed,iteration)
    rows = [r for r in rows if r['cls'] in ('none','faithful','misleading')]
Each row: model, scenario, arm, cls, seed, it(int 1..K), perf(float), best(float),
measured_speedup(float or None), applied(bool), correct(bool)
"""
from __future__ import annotations
import os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
from analyze_fleet import build_data, FAITH, fixed_perf_score  # noqa: E402

ARM_ORDER = ["none", "faithful", "misleading", "adversarial"]
ARM_COLOR = {
    "none": "#B0B7C3",
    "faithful": "#1A80BB",
    "misleading": "#A00000",
    "adversarial": "#600000",
}
ARM_LABEL = {"none": "none", "faithful": "candidate-derived feedback",
             "misleading": "baseline profile (legacy arm: misleading)",
             "adversarial": "adversarial (wrong)"}


def classify(arm: str) -> str:
    if arm == "none": return "none"
    if arm == "misleading": return "misleading"
    if arm == "adversarial": return "adversarial"
    if arm in FAITH: return "faithful"
    return "other"


def tidy(data=None, conditions=("OFF",), minimum_speedup=1.0):
    """Return fixed-gold tidy rows for the selected registry conditions."""
    data = data if data is not None else build_data(verbose=False)
    conditions = set(conditions)
    out = []
    for (model, cond), rows in data.items():
        if cond not in conditions:
            continue
        for x in rows:
            try: it = int(x.get("iteration") or 0)
            except Exception: it = 0
            correct = str(x.get("correct")).lower() == "true"
            try:
                measured_speedup = (float(x["measured_speedup"])
                                    if str(x.get("measured_speedup") or "").strip() else None)
            except (TypeError, ValueError):
                measured_speedup = None
            perf = fixed_perf_score(x)
            if minimum_speedup > 1.0:
                if measured_speedup is None or measured_speedup < minimum_speedup:
                    perf = 0.0
            out.append(dict(
                model=model, condition=cond, scenario=x["scenario_id"], arm=x["arm"], cls=classify(x["arm"]),
                seed=x.get("seed", "0"), it=it, perf=perf, best=0.0,
                measured_speedup=measured_speedup,
                applied=str(x.get("applied")).lower() == "true", correct=correct))
    # Recreate the within-cell running best from fixed-gold scores.  This is kept
    # for trajectory plots; cell-level analyses below take the max of ``perf``
    # directly and therefore cannot accidentally consume a stored best column.
    by_cell = defaultdict(list)
    for r in out:
        by_cell[(r["model"], r["scenario"], r["arm"], r["seed"])].append(r)
    for cell_rows in by_cell.values():
        running = 0.0
        for r in sorted(cell_rows, key=lambda item: item["it"]):
            running = max(running, r["perf"])
            r["best"] = running
    return out


def off_models(rows=None, min_scen=8):
    rows = rows if rows is not None else tidy()
    by = {}
    for r in rows:
        by.setdefault(r["model"], set()).add(r["scenario"])
    return sorted(m for m, s in by.items() if len(s) >= min_scen)


# Standard selectors (row -> bool). PRIMARY "correct" counterpart to `misleading` is the
# MATCHED faithful arm prof_cpu (same modality: func_profile/cpu, fresh) -- this is the rigorous
# comparison. SEL["faithful_pooled"] (all 5 faithful arms, max per cell) is a secondary view.
SEL = {
    "none":            lambda r: r["cls"] == "none",
    "faithful":        lambda r: r["arm"] == "prof_cpu",        # matched: fresh func_profile/cpu
    "faithful_pooled": lambda r: r["cls"] == "faithful",        # any faithful feedback (best per cell)
    "misleading":      lambda r: r["cls"] == "misleading",      # baseline func_profile/cpu
    "adversarial":     lambda r: r["cls"] == "adversarial",     # confidently-wrong (no data yet)
}


def best_per_cell(rows, sel):
    """Max best_perf_score per (model,scenario,seed) for rows matching selector `sel` (row->bool).
    Returns {(model,scenario,seed): best}. Pass SEL['misleading'] etc. or any predicate."""
    g = {}
    for r in rows:
        if not sel(r):
            continue
        k = (r["model"], r["scenario"], r["seed"])
        g[k] = max(g.get(k, 0.0), r["perf"])
    return g


def paired_by_scenario(rows, sel_a, sel_b):
    """Paired (a,b,model,scenario) best_perf_score per (model,scenario,seed) present in BOTH selectors."""
    A, B = best_per_cell(rows, sel_a), best_per_cell(rows, sel_b)
    return [(A[k], B[k], k[0], k[1]) for k in sorted(set(A) & set(B))]


if __name__ == "__main__":
    rows = tidy()
    ms = off_models(rows)
    print(f"rows={len(rows)} OFF models={ms}")
    for c in ("none", "faithful", "faithful_pooled", "misleading", "adversarial"):
        v = list(best_per_cell(rows, SEL[c]).values())
        print(f"  {c:16s} cells={len(v):4d} mean={sum(v)/len(v):.3f}" if v else f"  {c:16s} cells=0 (no data)")
    print(f"  paired(misleading,faithful=prof_cpu) n={len(paired_by_scenario(rows, SEL['misleading'], SEL['faithful']))}")
