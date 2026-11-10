#!/usr/bin/env python3
"""Canonical fleet analyzer for the perf panel (off vs apply-feedback ablation).

Single source of truth for the paper numbers. Reads volt-artifacts-fleet/JOB_REGISTRY.txt
(id -> model, condition), loads each job's retrieved CSV from volt-artifacts-fleet/byid/<id>/
(or any retrieved dir), combines A/B shards per (model, condition), and reports per-model:
  - apply rate, the 4-way outcome funnel (not-applied / broke-tests / correct-no-speedup /
    correct+faster), per-arm best perf_score, and none/faithful/misleading.
Then the cross-cutting findings: off-vs-on apply-feedback lift, and descriptive
fixed-gold fidelity summaries.

All performance scores are recomputed from ``measured_speedup`` and correctness
using the validated manifest's fixed gold speedup.  The stored ``perf_score`` and
``best_perf_score`` columns are deliberately ignored: older serving jobs used a
job-local live-gold normalizer.  Recorded speedups are rounded to three decimals,
so recomputed scores inherit that small quantization error.

CORRECTNESS GUARDS (printed): per (model,cond) it verifies the combined run covers the
expected scenarios, flags duplicate (scenario,arm,seed,iter) rows (shard overlap / stale
re-run data), and flags incomplete coverage (< expected scenarios). Dedup is applied before
metrics so a stale + fresh shard can't double-count.
"""
from __future__ import annotations
import csv, glob, json, collections, math, os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _first_existing(paths):
    for path in paths:
        if path.exists():
            return path
    raise FileNotFoundError("none of the expected analysis-snapshot paths exist: " +
                            ", ".join(str(path) for path in paths))


FLEET = _first_existing((
    HERE / "volt-artifacts-fleet",
    HERE / "artifact" / "volt-artifacts-fleet",
    HERE.parent / "volt-artifacts-fleet",
))
ANALYSIS_ROOT = FLEET.parent
REG = FLEET / "JOB_REGISTRY.txt"
FAITH = {"directional", "numbers", "benchstat", "prof_cpu", "prof_line"}
EXP_SCEN = 14  # validated panel size
VALIDATED_MANIFEST = _first_existing((
    ANALYSIS_ROOT / "manifests" / "perf_real_validated.json",
    HERE.parent / "manifests" / "perf_real_validated.json",
))


def _load_fixed_gold():
    manifest = json.loads(VALIDATED_MANIFEST.read_text(encoding="utf-8"))
    out = {}
    scenario_root = VALIDATED_MANIFEST.parent.parent
    for entry in manifest["scenarios"]:
        scenario = json.loads((scenario_root / entry["scenario"]).read_text(encoding="utf-8"))
        sid = scenario["scenario_id"]
        gold = float(scenario["evaluation"]["perf"]["gold_speedup"])
        if gold <= 1.0:
            raise ValueError(f"fixed gold must exceed 1.0 for {sid}: {gold}")
        out[sid] = gold
    if len(out) != EXP_SCEN:
        raise ValueError(f"validated manifest has {len(out)} scenarios, expected {EXP_SCEN}")
    return out


FIXED_GOLD = _load_fixed_gold()
SCORING_NOTE = (
    "fixed-gold rescoring from recorded measured_speedup + correctness; stored score columns ignored; "
    "recorded speedups are rounded to 3 decimals"
)


def fixed_perf_score(row):
    """Recompute the paper score from fixed manifest gold; never use stored scores."""
    sid = row["scenario_id"]
    if sid not in FIXED_GOLD:
        raise KeyError(f"row references scenario outside validated fixed-gold manifest: {sid}")
    if str(row.get("correct")).lower() != "true":
        return 0.0
    try:
        speedup = float(row.get("measured_speedup") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(speedup) or speedup <= 1.0:
        return 0.0
    return max(0.0, min(1.0, math.log(speedup) / math.log(FIXED_GOLD[sid])))


def find_csv(jid: str):
    pats = [f"{FLEET}/byid/{jid}/**/perfloop_*.csv", f"{FLEET}/**/{jid}/**/perfloop_*.csv"]
    for p in pats:
        fs = glob.glob(p, recursive=True)
        if fs:
            return fs[0]
    return None


def parse_registry():
    groups = collections.defaultdict(list)  # (model,cond) -> [ids]
    for line in REG.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        jid, model, cond = parts[0], parts[1], parts[2]
        groups[(model, cond)].append(jid)
    return groups


def load_group(ids):
    rows, missing = [], []
    for jid in ids:
        f = find_csv(jid)
        if not f:
            missing.append(jid); continue
        rows += list(csv.DictReader(open(f)))
    # dedup by (scenario,arm,seed,iteration) -- guards against shard overlap / stale re-run
    seen, dedup, dups = set(), [], 0
    for x in rows:
        k = (x["scenario_id"], x["arm"], x["seed"], x["iteration"])
        if k in seen:
            dups += 1; continue
        seen.add(k); dedup.append(x)
    return dedup, missing, dups


def cell_best(rows, pred):
    g = collections.defaultdict(float)
    for x in rows:
        if not pred(x["arm"]):
            continue
        v = fixed_perf_score(x)
        key = (x["scenario_id"], x["seed"], x["arm"])
        g[key] = max(g[key], v)
    return list(g.values())


def mean(v): return sum(v) / len(v) if v else 0.0


def funnel(rows):
    n = len(rows) or 1
    non = sum(1 for x in rows if str(x["applied"]).lower() != "true")
    err = sum(1 for x in rows if str(x["applied"]).lower() == "true" and str(x["correct"]).lower() != "true")
    cor_rows = [x for x in rows if str(x["applied"]).lower() == "true" and str(x["correct"]).lower() == "true"]
    fast = sum(1 for x in cor_rows if fixed_perf_score(x) > 0.0)
    cor_flat = len(cor_rows) - fast
    return dict(n=n, non=non/n, err=err/n, cor_flat=cor_flat/n, fast=fast/n, ap=(err+len(cor_rows))/n)


def build_data(verbose: bool = True):
    """Load + dedup every registry cell into {(model,cond): rows}. Single source of truth."""
    groups = parse_registry()
    data = {}
    if verbose:
        print("=== per (model, condition): coverage + funnel ===")
        print(f"{'model':14s} {'cond':5s} {'scen':>4} {'rows':>5} {'apply':>6} {'broke':>6} {'corr0':>6} {'faster':>7}  flags")
    for (model, cond), ids in sorted(groups.items()):
        rows, missing, dups = load_group(ids)
        if not rows:
            if verbose:
                print(f"{model:14s} {cond:5s}  -- no data (missing {len(missing)})")
            continue
        scen = len({x["scenario_id"] for x in rows})
        fu = funnel(rows)
        flags = []
        if scen < EXP_SCEN and cond in ("OFF", "ON"): flags.append(f"INCOMPLETE {scen}/{EXP_SCEN}")
        if dups: flags.append(f"DUPS={dups}")
        if missing: flags.append(f"missing_ids={len(missing)}")
        data[(model, cond)] = rows
        if verbose:
            print(f"{model:14s} {cond:5s} {scen:>4} {fu['n']:>5} {fu['ap']:>6.0%} {fu['err']:>6.0%} {fu['cor_flat']:>6.0%} {fu['fast']:>7.0%}  {' '.join(flags)}")
    return data


def main():
    print(f"SCORING: {SCORING_NOTE}")
    print(f"FIXED GOLD: {VALIDATED_MANIFEST.parent.name}/{VALIDATED_MANIFEST.name} "
          f"({len(FIXED_GOLD)} scenarios)")
    data = build_data(verbose=True)

    print("\n=== apply-feedback lift (OFF -> ON apply rate) ===")
    for model in sorted({m for (m, c) in data}):
        off, on = data.get((model, "OFF")), data.get((model, "ON"))
        if off and on:
            a0 = funnel(off)["ap"]; a1 = funnel(on)["ap"]
            print(f"  {model:14s} {a0:>5.0%} -> {a1:>5.0%}   (+{(a1-a0)*100:.0f} pts)")

    print("\n=== profile fidelity: none / prof_cpu / misleading / faithful_pooled [/ adversarial] (mean best perf_score, OFF arms) ===")
    pool = {"none": [], "prof": [], "m": [], "fp": [], "a": []}
    for model in sorted({m for (m, c) in data if c == "OFF"}):
        r = data[(model, "OFF")]
        no = cell_best(r, lambda a: a == "none")
        prof = cell_best(r, lambda a: a == "prof_cpu")
        fp = cell_best(r, lambda a: a in FAITH)
        mi = cell_best(r, lambda a: a == "misleading"); ad = cell_best(r, lambda a: a == "adversarial")
        pool["none"] += no; pool["prof"] += prof; pool["m"] += mi; pool["fp"] += fp; pool["a"] += ad
        tail = f"  adversarial {mean(ad):.3f}" if ad else ""
        print(f"  {model:14s} none {mean(no):.3f}  prof_cpu {mean(prof):.3f}  misleading {mean(mi):.3f}  faithful_pooled {mean(fp):.3f}{tail}")
    atail = f"  adversarial {mean(pool['a']):.3f}" if pool["a"] else ""
    print(f"  {'POOLED':14s} none {mean(pool['none']):.3f}  prof_cpu {mean(pool['prof']):.3f}  misleading {mean(pool['m']):.3f}  faithful_pooled {mean(pool['fp']):.3f}{atail}")


if __name__ == "__main__":
    main()
