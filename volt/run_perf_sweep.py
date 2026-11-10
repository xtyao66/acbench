#!/usr/bin/env python3
"""Measured-speedup model sweep (AI for Performance Engineering).

For each measured-perf scenario x diagnosis-condition x seed: the code agent gets a
profiling diagnosis (none/gold/wrong/gold_noleak/...) and produces an optimization
patch. We apply it, gate on BEHAVIORAL correctness (the pass_to_pass guards only --
not the specific counting test, so any valid optimization counts), then MEASURE the
wall-clock speedup it achieves on THIS hardware via bench.py (min-of-K). perf_score
= fraction of the gold optimization's log-speedup the agent reached (0 if it broke
correctness). Reuses run_experiments (serving + diagnosis builders) and measure_perf
(bench + patch apply). One CSV row per (scenario, condition, seed).
"""
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_experiments as RE   # serve_vllm, wait_health, gold_diag, gold_noleak_diag, ...
import measure_perf as MP      # run_bench, apply_patch

CODE = RE.CODE_DIR
ARTIFACTS = RE.ARTIFACTS
MODEL_ID = RE.MODEL_ID
SEEDS = RE.SEEDS
TEMPERATURE = RE.TEMPERATURE
BASE_URL = RE.BASE_URL
CONDITIONS = RE.CONDITIONS  # honors ACBENCH_CONDITIONS filter
MANIFEST = os.environ.get("ACBENCH_MANIFEST", "manifests/perf_measured.json")
SMOKE = os.environ.get("ACBENCH_PERF_SMOKE") == "1"  # use gold patch instead of the model (local test)


def log(m: str) -> None:
    print(f"[acbench-perf] {m}", flush=True)


def perf_score(speedup, gold_speedup):
    if not speedup or speedup <= 1.0:
        return 0.0
    if gold_speedup <= 1.0:
        return 1.0
    return max(0.0, min(1.0, math.log(speedup) / math.log(gold_speedup)))


def behavioral_ok(repo, pass_to_pass):
    """Run ONLY the pass_to_pass behavioral guards (by method name) -- correctness gate."""
    methods = [tid.split("::")[-1] for tid in (pass_to_pass or [])]
    if not methods:
        return True
    expr = " or ".join(sorted(set(methods)))
    p = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-k", expr, "-q"],
                       cwd=repo, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "src"})
    return p.returncode == 0


def measure(repo):
    try:
        return MP.run_bench(repo)
    except Exception as exc:
        log(f"bench failed in {repo}: {exc}")
        return None


def extract_diff(text: str) -> str:
    """Pull the unified-diff portion out of an LLM response (strip prose/markdown
    fences/reasoning), so `git apply` sees a clean diff. The naive path failed
    because models wrap diffs in ``` fences or chatter that git apply rejects."""
    if not text:
        return ""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.startswith("diff --git ") or l.startswith("--- ")), None)
    if start is None:
        return text
    out = [l for l in lines[start:] if not l.lstrip().startswith("```")]
    return "\n".join(out).rstrip() + "\n"


def robust_apply(repo: Path, patch_text: str) -> bool:
    """Extract the diff, then apply with git (recount handles line drift) + patch
    fuzz fallback. Strictly more robust than naive git-apply or the executor's
    hand-rolled parser."""
    diff = extract_diff(patch_text)
    if not diff.strip():
        return False
    pf = repo.parent / "_agent.diff"
    pf.write_text(diff, encoding="utf-8")
    for cmd in (["git", "apply", "--recount", "-p1", str(pf)],
                ["git", "apply", "-p1", str(pf)],
                ["git", "apply", "--recount", "-p0", str(pf)],
                ["patch", "-p1", "--fuzz=3", "-i", str(pf)]):
        try:
            if subprocess.run(cmd, cwd=repo, capture_output=True, text=True).returncode == 0:
                return True
        except FileNotFoundError:
            continue
    return False


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    subprocess.run("apt-get update -qq && apt-get install -y -qq git patch >/dev/null 2>&1 || true", shell=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(CODE)], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pytest", "numpy"], check=False)
    sys.path.insert(0, str(CODE))
    from acbench.models.scenario import ScenarioSpec
    from acbench.models.runtime import RunConfig
    from acbench.agents.openai_code import OpenAICodePatchAgent  # noqa: F401 (ref used by executor)
    from acbench.executors.local_code import LocalCodeExecutor
    from acbench.executors.backends.ops.runtime import NativeOpsProblem
    os.environ.setdefault("OPENAI_API_KEY", "EMPTY")

    entries = json.loads((CODE / MANIFEST).read_text())["scenarios"]
    raw = [json.loads((CODE / e["scenario"]).read_text()) for e in entries]
    specs = [ScenarioSpec.from_file(CODE / e["scenario"]) for e in entries]

    vllm = None if SMOKE else RE.serve()
    rows = []
    out = ARTIFACTS / f"perfsweep_{MODEL_ID.split('/')[-1]}.csv"
    fields = ["model", "scenario_id", "condition", "diag_kind", "seed", "patch_chars", "applied", "correct",
              "measured_speedup", "gold_speedup", "perf_score", "base_ms", "cand_ms"]
    try:
        if not SMOKE:
            RE.wait_health()
        for idx, (rawd, s) in enumerate(zip(raw, specs)):
            fix = CODE / s.service.repository_path
            if not (fix / "bench.py").exists():
                log(f"skip {s.scenario_id}: no bench.py"); continue
            gold_patch = (CODE / rawd.get("gold_patch_path", "")).resolve()
            p2p = (s.evaluation.pass_to_pass or [])
            # per-scenario references (measure once): baseline + gold speedup
            with tempfile.TemporaryDirectory() as td:
                base = Path(td) / "base"; shutil.copytree(fix, base)
                t_base = measure(base)
                gc = Path(td) / "gold"; shutil.copytree(fix, gc)
                gold_ok = MP.apply_patch(gc, gold_patch) and behavioral_ok(gc, p2p)
                t_gold = measure(gc) if gold_ok else None
            gold_speedup = (t_base / t_gold) if (t_base and t_gold) else 1.0
            log(f"{s.scenario_id}: base={ (t_base or 0)*1000:.0f}ms  gold_speedup={gold_speedup:.1f}x")
            # perf_score saturates to 1.0 for any speedup when gold_speedup <= 1.0, so a gold
            # that does not apply, breaks the guards or is not faster cannot normalize scores.
            if not gold_ok or gold_speedup <= 1.0:
                log(f"skip {s.scenario_id}: unusable gold reference (applied+correct={gold_ok})")
                continue
            problem = NativeOpsProblem.from_scenario(s) if s.ops_fault else None
            gold = RE.gold_diag(problem) if problem else {}
            wp = NativeOpsProblem.from_scenario(specs[(idx + 1) % len(specs)]) if specs[(idx + 1) % len(specs)].ops_fault else None
            wrong = RE.gold_diag(wp) if wp else {}
            for cond, hide, kind in CONDITIONS:
                for seed in SEEDS:
                    if kind == "none":
                        diag = None
                    elif kind == "gold":
                        diag = gold
                    elif kind == "gold_noleak":
                        diag = RE.gold_noleak_diag(gold, s)
                    elif kind == "wrong":
                        diag = wrong
                    elif kind == "filler":
                        diag = RE.filler_diag()
                    elif kind.startswith("comp_"):
                        diag = RE.component_diag(problem, kind[len("comp_"):])
                    else:
                        diag = None
                    rc = RunConfig(
                        openai_model=MODEL_ID, openai_base_url=BASE_URL, openai_api_key_env="OPENAI_API_KEY",
                        code_agent_config={"api": "chat_completions", "temperature": TEMPERATURE, "seed": seed},
                        upstream_ops_diagnosis=diag, hide_fault_location=hide,
                    )
                    applied = correct = False
                    t_cand = None
                    with tempfile.TemporaryDirectory() as td:
                        if SMOKE:
                            patch = gold_patch.read_text(encoding="utf-8")
                        else:
                            try:
                                res = OpenAICodePatchAgent().generate_patch(s, rc, output_dir=Path(td))
                                patch = (res.get("patch_text") or "") if isinstance(res, dict) else ""
                            except Exception as exc:
                                log(f"agent fail {s.scenario_id}/{cond}/{seed}: {exc}"); patch = ""
                        cand = Path(td) / "cand"; shutil.copytree(fix, cand)
                        applied = robust_apply(cand, patch)
                        correct = behavioral_ok(cand, p2p) if applied else False
                        t_cand = measure(cand) if correct else None
                    sp = (t_base / t_cand) if (correct and t_cand and t_base) else (None if correct else 0.0)
                    score = perf_score(sp, gold_speedup) if correct else 0.0
                    rows.append({
                        "model": MODEL_ID, "scenario_id": s.scenario_id, "condition": cond,
                        "diag_kind": kind, "seed": seed, "patch_chars": len(patch or ""), "applied": applied, "correct": correct,
                        "measured_speedup": round(sp, 2) if sp else sp,
                        "gold_speedup": round(gold_speedup, 2), "perf_score": round(score, 3),
                        "base_ms": round(t_base * 1000, 1) if t_base else None,
                        "cand_ms": round(t_cand * 1000, 2) if t_cand else None,
                    })
            with out.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
            log(f"done {s.scenario_id} ({len(rows)} rows)")
    finally:
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
        log(f"wrote {out} ({len(rows)} rows)")
        if vllm and vllm.poll() is None:
            vllm.terminate()
            try:
                vllm.wait(timeout=30)
            except subprocess.TimeoutExpired:
                vllm.kill()


if __name__ == "__main__":
    main()
