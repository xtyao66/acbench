#!/usr/bin/env python3
"""Measured-performance grading for ACBench perf scenarios.

For each scenario in a manifest: set up the fixture (baseline) and a candidate
(gold patch by default, or an agent patch), gate on correctness, then run the
fixture's bench.py on the SAME hardware K times and take the MIN elapsed
(interference-free best). Speedup = baseline_min / candidate_min. Writes one row
per scenario. Hardware-agnostic: run the same job on any Volt machine_type.
"""
import csv, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

CODE = Path(os.environ.get("ACBENCH_CODE_DIR", "."))
MAN  = os.environ.get("PERF_MANIFEST", "manifests/perf_combined.json")
REPS = int(os.environ.get("PERF_REPS", "7"))
WARM = int(os.environ.get("PERF_WARMUP", "2"))
OUT  = Path(os.environ.get("PERF_OUT", "perf_measure.csv"))

def run_bench(repo):
    env = {**os.environ, "PYTHONPATH": "src"}
    best = None
    for i in range(REPS + WARM):
        p = subprocess.run([sys.executable, "bench.py"], cwd=repo, capture_output=True, text=True, env=env)
        if p.returncode != 0:
            raise RuntimeError("bench failed: " + p.stderr[-300:])
        d = json.loads(p.stdout.strip().splitlines()[-1])
        if i >= WARM:
            best = d["elapsed_s"] if best is None else min(best, d["elapsed_s"])
    return best

def correctness_ok(repo):
    p = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"], cwd=repo,
                       capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "src"})
    return p.returncode == 0

def apply_patch(repo, patch):
    for cmd in (["git", "apply", str(patch)], ["patch", "-p1", "-i", str(patch)]):
        try:
            r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
            if r.returncode == 0:
                return True
        except FileNotFoundError:
            continue  # tool not installed; try the next
    return False

def main():
    man = json.loads((CODE / MAN).read_text())
    rows = []
    for e in man["scenarios"]:
        sc = json.loads((CODE / e["scenario"]).read_text())
        fix = CODE / sc["service"]["repository_path"]
        gold = (CODE / sc.get("gold_patch_path", "")).resolve()
        sid = sc["scenario_id"]
        if not (fix / "bench.py").exists():
            print(f"skip {sid}: no bench.py"); continue
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "base"; shutil.copytree(fix, base)
            cand = Path(td) / "cand"; shutil.copytree(fix, cand)
            applied = apply_patch(cand, gold)
            corr = correctness_ok(cand)
            tb = run_bench(base); tc = run_bench(cand)
            sp = (tb / tc) if tc else 0.0
            rows.append({"scenario_id": sid, "gold_apply": applied, "correctness_pass": corr,
                         "base_ms": round(tb*1000, 2), "cand_ms": round(tc*1000, 3),
                         "speedup": round(sp, 1)})
            print(f"  {sid:42s} {tb*1000:8.1f} -> {tc*1000:7.2f} ms   {sp:8.1f}x   correct={corr}")
    if rows:
        with OUT.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        print("wrote", OUT)
if __name__ == "__main__":
    main()
