#!/usr/bin/env python3
"""Model-free gold-speedup validation for candidate perf scenarios.

For each scenario in ACBENCH_MANIFEST: clone @ base_commit (+bench patch), measure the
baseline benchmark, apply the gold fix, gate on `go test` correctness, then measure the
gold speedup (benchstat-style geomean of per-sub-benchmark ratios, min-of-K). Prints a
per-scenario verdict and writes gold_validation.json so build-fails / washouts (<keep
threshold) / test-breakers are dropped before they enter the benchmark. No GPU needed --
reuses measure_perf_go (the run_perf_real grader: min over separate `-count 1` runs). The
perf loop (run_perf_loop) measures with perf_profile.bench_numbers instead (one `-count N`
run), so its live gold speedup can differ somewhat from the value validated here.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MANIFEST = os.environ.get("ACBENCH_MANIFEST", "manifests/perf_real_candidates.json")
KEEP = float(os.environ.get("ACBENCH_GOLD_MIN", "1.15"))
ARTIFACTS = Path(os.environ.get("volt_artifacts", os.environ.get("VOLT_ARTIFACTS", "/volt/artifacts")))

_spec = importlib.util.spec_from_file_location("mpg", HERE / "measure_perf_go.py")
MPG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MPG)  # go_measure, speedup, go_correct, apply_patch, mat


def log(m: str) -> None:
    print(f"[validate-gold] {m}", flush=True)


def validate_one(rel: str) -> dict:
    d = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    sid = d["scenario_id"]
    perf = d["evaluation"]["perf"]
    pkg, bench = perf["pkg"], perf["benchmark"]
    r = {"sid": sid, "stage": "start", "speedup": None, "n_subbench": 0}
    try:
        base = Path(MPG.mat.materialize_one(rel, patch_suffix="bench", require_patch=False))
        base_ns = MPG.go_measure(base, pkg, bench)
        r["n_subbench"] = len(base_ns)
        if not base_ns:
            r["stage"] = "base_NO_subbench"; return r
        with tempfile.TemporaryDirectory() as td:
            gc = Path(td) / "gold"
            shutil.copytree(base, gc)
            if not MPG.apply_patch(gc, ROOT / "patches" / f"{sid}_fix.diff"):
                r["stage"] = "gold_APPLY_failed"; return r
            if not MPG.go_correct(gc, pkg, None):
                r["stage"] = "gold_CORRECT_failed"; return r
            gns = MPG.go_measure(gc, pkg, bench)
            sp = MPG.speedup(base_ns, gns)
            r["speedup"] = round(sp, 3)
            r["stage"] = "OK" if sp >= KEEP else "WASHOUT"
    except Exception as exc:  # noqa: BLE001
        r["stage"] = f"ERROR: {str(exc)[:200]}"
    return r


def main() -> None:
    subprocess.run("apt-get update -qq && apt-get install -y -qq git gcc curl ca-certificates >/dev/null 2>&1 || true", shell=True)
    man = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))["scenarios"]
    log(f"validating {len(man)} candidates (keep speedup>={KEEP}x AND gold applies+correct)")
    results = []
    for e in man:
        r = validate_one(e["scenario"])
        log(f"  {r['sid']}: {r['stage']} speedup={r['speedup']} subbench={r['n_subbench']}")
        results.append(r)
    try:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        (ARTIFACTS / "gold_validation.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log(f"(could not write artifacts json: {exc})")
    keep = [r for r in results if r["stage"] == "OK"]
    log("=== SUMMARY ===")
    log(f"KEEP {len(keep)}/{len(results)}: " + ", ".join(f"{r['sid']}={r['speedup']}x" for r in keep))
    for r in results:
        if r["stage"] != "OK":
            log(f"  DROP {r['sid']}: {r['stage']} (speedup={r['speedup']})")


if __name__ == "__main__":
    main()
