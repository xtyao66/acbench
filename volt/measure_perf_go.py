#!/usr/bin/env python3
"""Measured-performance grading for REAL Go optimization PRs.

speedup = baseline_min_ns_per_op / candidate_min_ns_per_op, where ns/op is read
from ``go test -bench`` (min over PERF_REPS independent runs, the interference-free
best), gated on behavior preservation (``go test`` of the package / pass_to_pass).

Smoke mode (this file's main): for every scenario in the perf manifest, grade the
GOLD optimization (base vs gold), confirming a real, reproducible speedup with
behavior preserved. A green smoke validates that real Go optimization PRs are
gradeable by measured speedup before any GPU is spent. The measured gold speedup
is also emitted so it can be baked into each scenario as the perf_score normalizer.

Each perf scenario carries ``evaluation.perf = {pkg, benchmark, pass_to_pass?,
gold_speedup?}``. Scenarios whose benchmark was ADDED by the PR get a
``<sid>_bench.diff`` applied at base; pre-existing benchmarks need none.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MANIFEST = os.environ.get("PERF_MANIFEST", "manifests/perf_real.json")
REPS = int(os.environ.get("PERF_REPS", "5"))
BENCHTIME = os.environ.get("PERF_BENCHTIME", "1s")
OUT = Path(os.environ.get("PERF_OUT", "perf_real_smoke.csv"))

_spec = importlib.util.spec_from_file_location("materialize_real", ROOT / "volt" / "materialize_real.py")
mat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mat)  # type: ignore[union-attr]

# Capture (benchmark-name-with-GOMAXPROCS-suffix, ns/op) so multi-sub-benchmark
# cases are matched by name across base/candidate instead of min'd together.
BENCH_RE = re.compile(r"^(Benchmark\S+)\s+\d+\s+([\d.]+)\s+ns/op", re.M)


def go_measure(repo: Path, pkg: str, bench: str, reps: int = REPS) -> dict:
    """Return {sub_benchmark_name: min ns/op over `reps` runs}."""
    acc: dict[str, float] = {}
    last = ""
    for _ in range(reps):
        p = subprocess.run(
            ["go", "test", "-run", "^$", "-bench", f"^{bench}$", "-benchmem",
             "-benchtime", BENCHTIME, "-count", "1", f"./{pkg}"],
            cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        last = (p.stdout + p.stderr)[-400:]
        # A non-zero exit means the benchmark panicked/failed (often only on the
        # expensive sub-cases). Do NOT keep the partial sub-benchmarks that printed
        # before the crash — that would credit a "speedup" over the survivors only.
        if p.returncode != 0:
            raise RuntimeError(f"benchmark {bench} failed (rc={p.returncode}) in {pkg}: {last}")
        for name, ns in BENCH_RE.findall(p.stdout):
            v = float(ns)
            acc[name] = v if name not in acc else min(acc[name], v)
    if not acc:
        raise RuntimeError(f"no ns/op for {bench} in {pkg}: {last}")
    return acc


def speedup(base: dict, cand: dict) -> float:
    """Geomean of per-sub-benchmark base/cand ns ratios (benchstat-style).

    Requires the candidate to keep EVERY base sub-benchmark — a candidate that
    drops/renames/crashes an (expensive) sub-benchmark is not credited a speedup
    over the cheap survivors; it scores 0.
    """
    if any(k not in cand for k in base):
        return 0.0
    common = [k for k in base if cand.get(k, 0) > 0 and base[k] > 0]
    if not common:
        return 0.0
    return math.exp(sum(math.log(base[k] / cand[k]) for k in common) / len(common))


def go_correct(repo: Path, pkg: str, tests=None) -> bool:
    cmd = ["go", "test", "-count", "1"]
    if tests:
        cmd += ["-run", "^(" + "|".join(tests) + ")$"]
    cmd += [f"./{pkg}"]
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").returncode == 0


def apply_patch(repo: Path, patch: Path) -> bool:
    for cmd in (["git", "apply", "--whitespace=nowarn", str(patch)], ["patch", "-p1", "-i", str(patch)]):
        if subprocess.run(cmd, cwd=repo, capture_output=True, text=True).returncode == 0:
            return True
    return False


def main() -> int:
    man = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    rows = []
    ok = 0
    for e in man["scenarios"]:
        rel = e["scenario"]
        d = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        sid = d["scenario_id"]
        perf = d["evaluation"]["perf"]
        pkg, bench = perf["pkg"], perf["benchmark"]
        try:
            base = mat.materialize_one(rel, patch_suffix="bench", require_patch=False)
        except Exception as exc:  # noqa: BLE001
            print(f"XX {sid}: materialize failed: {exc}", flush=True)
            continue
        cand = Path(tempfile.mkdtemp(prefix=f"perf_{sid}_"))
        subprocess.run(f"tar --exclude=.git -C {base} -cf - . | tar -C {cand} -xf -", shell=True, check=True)
        gold = ROOT / "patches" / f"{sid}_fix.diff"
        applied = apply_patch(cand, gold)
        corr = go_correct(cand, pkg, perf.get("pass_to_pass"))
        try:
            tb = go_measure(base, pkg, bench)
            tc = go_measure(cand, pkg, bench)
            sp = speedup(tb, tc)
        except Exception as exc:  # noqa: BLE001
            print(f"XX {sid}: measure failed: {exc}", flush=True)
            shutil.rmtree(cand, ignore_errors=True)
            continue
        n_sub = len([k for k in tb if k in tc])
        gm_base = math.exp(sum(math.log(v) for v in tb.values()) / len(tb))
        gm_cand = math.exp(sum(math.log(v) for v in tc.values()) / len(tc))
        good = applied and corr and sp >= 1.05
        if good:
            ok += 1
        print(f"{'OK ' if good else 'XX '} {sid:30s} {gm_base:12.0f} -> {gm_cand:12.0f} ns/op(gm)  "
              f"{sp:6.2f}x  subbench={n_sub} applied={applied} correct={corr}", flush=True)
        rows.append({"scenario_id": sid, "pkg": pkg, "benchmark": bench,
                     "base_ns_gm": round(gm_base, 1), "gold_ns_gm": round(gm_cand, 1),
                     "speedup": round(sp, 3), "n_subbench": n_sub, "applied": applied, "correct": corr})
        shutil.rmtree(cand, ignore_errors=True)
    if rows:
        with OUT.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"\nPERF SMOKE: {ok}/{len(rows)} real optimization PRs show measured speedup "
          f"(gold faster + behavior preserved).", flush=True)
    print("GOLD_SPEEDUPS " + json.dumps({r["scenario_id"]: r["speedup"] for r in rows}), flush=True)
    return 0 if ok == len(rows) and rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
