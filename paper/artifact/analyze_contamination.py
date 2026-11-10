#!/usr/bin/env python3
"""Contamination probe: do model patches reproduce the public human fix verbatim?
For each (model, scenario) we take the best CORRECT emitted patch (captured via
ACBENCH_CAPTURE_PATCHES=1 -> perfloop_patches_*.jsonl) and measure its overlap with the human
merged-PR fix (patches/<sid>_fix.diff). High overlap is a memorization risk signal.
Run: python3 paper/analyze_contamination.py
"""
from __future__ import annotations
import json, glob, os, sys, difflib
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if not os.path.exists(os.path.join(ROOT, "volt-artifacts-fleet")) and os.path.exists(os.path.join(HERE, "volt-artifacts-fleet")):
    ROOT = HERE

def norm(d: str) -> str:
    # keep only changed code lines (+/-), strip markers/whitespace -> comparable content
    out = []
    for l in d.splitlines():
        if l[:2] in ("++", "--") or not l or l[0] not in "+-":
            continue
        out.append(l[1:].strip())
    return "\n".join(x for x in out if x)

pat = defaultdict(list)  # (model, sid) -> [(perf, correct, diff)]
files = glob.glob(os.path.join(ROOT, "volt-artifacts-fleet/**/perfloop_patches_*.jsonl"), recursive=True)
for f in files:
    for line in open(f, encoding="utf-8", errors="replace"):
        try: r = json.loads(line)
        except Exception: continue
        pat[(r["model"].split("/")[-1], r["scenario_id"])].append(
            (r.get("perf_score", 0.0), bool(r.get("correct")), r.get("diff", "")))

if not pat:
    print(f"no captured patches yet (found {len(files)} jsonl files). Re-run after the rc jobs land."); sys.exit(0)

rows = []
for (model, sid), lst in sorted(pat.items()):
    corr = [(p, d) for (p, c, d) in lst if c and d.strip()]
    if not corr:
        continue
    best = max(corr, key=lambda x: x[0])[1]      # highest-perf correct emitted patch
    goldf = os.path.join(ROOT, f"patches/{sid}_fix.diff")
    if not os.path.exists(goldf):
        continue
    gold = open(goldf, encoding="utf-8", errors="replace").read()
    sim = difflib.SequenceMatcher(None, norm(best), norm(gold)).ratio()
    rows.append((model, sid, sim))

if not rows:
    print("patches present but no (correct-patch, gold-fix) pairs matched. Check patches/<sid>_fix.diff paths."); sys.exit(0)

print(f"=== CONTAMINATION: best-correct emitted patch vs human fix overlap (n={len(rows)} cells) ===")
by_model = defaultdict(list)
for m, s, sim in rows: by_model[m].append(sim)
for m in sorted(by_model):
    v = by_model[m]
    hi = sum(1 for x in v if x >= 0.6)
    print(f"  {m:16s} n={len(v):2d}  mean overlap={sum(v)/len(v):.2f}  median={sorted(v)[len(v)//2]:.2f}  high(>=0.6)={hi}/{len(v)}")
allv = [x for _, _, x in rows]
allv.sort()
hi = sum(1 for x in allv if x >= 0.6)
print(f"  POOLED n={len(allv)}  mean={sum(allv)/len(allv):.2f}  median={allv[len(allv)//2]:.2f}  high-overlap(>=0.6)={hi}/{len(allv)} ({100*hi/len(allv):.0f}%)")
print("\nInterpretation: low mean overlap and few high-overlap cells are evidence against widespread")
print("verbatim reproduction of the human diffs among captured successful patches. This does not rule")
print("out training-data contamination or non-verbatim recall.")
