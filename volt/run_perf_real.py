#!/usr/bin/env python3
"""Measured-speedup model leaderboard on REAL Go optimization PRs.

The Go analog of run_perf_sweep.py. For each real perf scenario x diagnosis-condition
x seed: the code agent gets a PROFILING diagnosis (none/gold/wrong/gold_noleak) + the
slow file, and produces an optimization patch. We apply it (robust), gate on
``go test`` behavioral correctness, then MEASURE the speedup via ``go test -bench``
(geomean of per-sub-benchmark ns ratios, min-of-K). perf_score = fraction of the gold
optimization's log-speedup the agent reached (0 if it broke behavior). Reuses
run_experiments (serving + diagnosis builders), run_perf_sweep (robust_apply,
perf_score), and measure_perf_go (go_measure/speedup/go_correct + materialization).
One CSV row per (scenario, condition, seed).
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_experiments as RE          # serve_vllm, wait_health, gold_diag, gold_noleak_diag, CONDITIONS, ...
import run_perf_sweep as PS           # robust_apply, extract_diff, perf_score

_pg = importlib.util.spec_from_file_location("mpg", HERE / "measure_perf_go.py")
MPG = importlib.util.module_from_spec(_pg)
_pg.loader.exec_module(MPG)           # go_measure, speedup, go_correct, mat (materialize_real)

CODE = RE.CODE_DIR
ARTIFACTS = RE.ARTIFACTS
MODEL_ID = RE.MODEL_ID
SEEDS = RE.SEEDS
TEMPERATURE = RE.TEMPERATURE
BASE_URL = RE.BASE_URL
CONDITIONS = RE.CONDITIONS  # honors ACBENCH_CONDITIONS
MANIFEST = os.environ.get("ACBENCH_MANIFEST", "manifests/perf_real_validated.json")
SMOKE = os.environ.get("ACBENCH_PERF_SMOKE") == "1"


def log(m: str) -> None:
    print(f"[acbench-perfreal] {m}", flush=True)


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(CODE)], check=True)
    sys.path.insert(0, str(CODE))
    from acbench.models.scenario import ScenarioSpec
    from acbench.models.runtime import RunConfig
    from acbench.agents.openai_code import OpenAICodePatchAgent  # noqa: F401
    from acbench.executors.backends.ops.runtime import NativeOpsProblem
    from acbench.executors.backends.code.standalone import apply_patch as std_apply
    from acbench.executors.local_code import patch_modified_paths, forbidden_path_violations
    os.environ.setdefault("OPENAI_API_KEY", "EMPTY")

    entries = json.loads((CODE / MANIFEST).read_text())["scenarios"]
    raw = [json.loads((CODE / e["scenario"]).read_text()) for e in entries]
    specs = [ScenarioSpec.from_file(CODE / e["scenario"]) for e in entries]
    rels = [e["scenario"] for e in entries]

    vllm = None if SMOKE else RE.serve()
    rows = []
    out = ARTIFACTS / f"perfreal_{MODEL_ID.split('/')[-1]}.csv"
    fields = ["model", "scenario_id", "condition", "diag_kind", "seed", "patch_chars",
              "applied", "correct", "measured_speedup", "gold_speedup", "perf_score", "n_subbench"]
    try:
        if not SMOKE:
            RE.wait_health()
        for idx, (rawd, s, rel) in enumerate(zip(raw, specs, rels)):
            perf = rawd["evaluation"]["perf"]
            pkg, bench = perf["pkg"], perf["benchmark"]
            try:
                base = Path(MPG.mat.materialize_one(rel, patch_suffix="bench", require_patch=False))
                base_meas = MPG.go_measure(base, pkg, bench)
            except Exception as exc:  # noqa: BLE001
                log(f"skip {s.scenario_id}: base setup failed: {exc}")
                continue
            # Measure the GOLD (expert) optimization LIVE on THIS hardware as the
            # perf_score normalizer. The baked gold_speedup was measured on a
            # different (x86) box and must not normalize arm64 measurements.
            gold_speedup = perf.get("gold_speedup") or 1.0
            try:
                with tempfile.TemporaryDirectory() as gtd:
                    gc = Path(gtd) / "gold"
                    shutil.copytree(base, gc)
                    if MPG.apply_patch(gc, CODE / "patches" / f"{s.scenario_id}_fix.diff") \
                            and MPG.go_correct(gc, pkg, perf.get("pass_to_pass")):
                        live = MPG.speedup(base_meas, MPG.go_measure(gc, pkg, bench))
                        if live and live > 1.0:
                            gold_speedup = live
            except Exception as exc:  # noqa: BLE001
                log(f"{s.scenario_id}: live gold measure failed, using baked {gold_speedup}: {exc}")
            log(f"{s.scenario_id}: gold_speedup(live)={gold_speedup:.2f}x "
                f"(baked {perf.get('gold_speedup')}), base sub-benchmarks={len(base_meas)}")
            problem = NativeOpsProblem.from_scenario(s) if s.ops_fault else None
            gold = RE.gold_diag(problem) if problem else {}
            wp_spec = specs[(idx + 1) % len(specs)]
            wrong = RE.gold_diag(NativeOpsProblem.from_scenario(wp_spec)) if wp_spec.ops_fault else {}

            for cond, hide, kind in CONDITIONS:
                for seed in SEEDS:
                    if kind == "gold":
                        diag = gold
                    elif kind == "gold_noleak":
                        diag = RE.gold_noleak_diag(gold, s)
                    elif kind == "wrong":
                        diag = wrong
                    elif kind == "filler":
                        diag = RE.filler_diag()
                    else:  # none / model(unsupported here) -> no injected diagnosis
                        diag = None
                    rc = RunConfig(
                        openai_model=MODEL_ID, openai_base_url=BASE_URL, openai_api_key_env="OPENAI_API_KEY",
                        code_agent_config={"api": "chat_completions", "temperature": TEMPERATURE, "seed": seed},
                        upstream_ops_diagnosis=diag, hide_fault_location=hide,
                    )
                    applied = correct = False
                    sp = None
                    n_sub = 0
                    with tempfile.TemporaryDirectory() as td:
                        if SMOKE:
                            patch = (CODE / "patches" / f"{s.scenario_id}_fix.diff").read_text(encoding="utf-8")
                        else:
                            try:
                                res = OpenAICodePatchAgent().generate_patch(s, rc, output_dir=Path(td))
                                patch = (res.get("patch_text") or "") if isinstance(res, dict) else ""
                            except Exception as exc:  # noqa: BLE001
                                log(f"agent fail {s.scenario_id}/{cond}/{seed}: {exc}")
                                patch = ""
                        cand = Path(td) / "cand"
                        shutil.copytree(base, cand)
                        # Use the SAME lenient subsequence-matcher as the correctness
                        # real-PR run (cand has no .git -> std_apply -> apply_patch_without_git),
                        # so the two axes apply agent diffs identically. extract_diff strips
                        # prose/fences first. (robust_apply's strict git apply zeroed gpt-oss.)
                        diff = PS.extract_diff(patch)
                        applied = False
                        forbidden = list(s.evaluation.forbidden_paths or [])
                        if diff.strip():
                            # Reject patches that touch the benchmark/test (oracle) files —
                            # the agent must not edit what it is measured by. (The correctness
                            # path enforces this; the perf path previously did not.)
                            if forbidden_path_violations(patch_modified_paths(diff), forbidden):
                                applied = False
                            else:
                                pf = Path(td) / "_agent.diff"
                                pf.write_text(diff, encoding="utf-8")
                                applied, _ = std_apply(cand, pf)
                        if applied:
                            # Restore the canonical benchmark/test files from base so the
                            # measured benchmark is always the one we baked (defense in depth).
                            for fp in forbidden:
                                src, dst = base / fp, cand / fp
                                if src.exists():
                                    dst.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copy2(src, dst)
                        correct = MPG.go_correct(cand, pkg, perf.get("pass_to_pass")) if applied else False
                        if correct:
                            try:
                                cand_meas = MPG.go_measure(cand, pkg, bench)
                                sp = MPG.speedup(base_meas, cand_meas)
                                n_sub = len([k for k in base_meas if k in cand_meas])
                            except Exception as exc:  # noqa: BLE001
                                log(f"cand measure fail {s.scenario_id}/{cond}/{seed}: {exc}")
                                sp = None
                    score = PS.perf_score(sp, gold_speedup) if (correct and sp) else 0.0
                    rows.append({
                        "model": MODEL_ID, "scenario_id": s.scenario_id, "condition": cond,
                        "diag_kind": kind, "seed": seed, "patch_chars": len(patch or ""),
                        "applied": applied, "correct": correct,
                        "measured_speedup": round(sp, 3) if sp else sp,
                        "gold_speedup": round(gold_speedup, 2), "perf_score": round(score, 3),
                        "n_subbench": n_sub,
                    })
            with out.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=fields)
                w.writeheader()
                w.writerows(rows)
            log(f"done {s.scenario_id} ({len(rows)} rows)")
    finally:
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        log(f"wrote {out} ({len(rows)} rows)")
        if vllm and vllm.poll() is None:
            vllm.terminate()
            try:
                vllm.wait(timeout=30)
            except subprocess.TimeoutExpired:
                vllm.kill()


if __name__ == "__main__":
    main()
