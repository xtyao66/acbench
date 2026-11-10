#!/usr/bin/env python3
"""Performance-feedback-fidelity study: agentic optimization LOOP on real Go PRs.

For each (scenario x feedback-arm x seed), the agent runs a K-iteration loop:
  propose patch -> apply (lenient) -> correctness gate -> measure speedup
  (+ collect the profiling artifacts the arm needs) -> render feedback at the
  arm's FIDELITY LEVEL / MODALITY -> next iteration.

The ONLY thing that differs across arms is the feedback string (perf_feedback).
Compute budget (K iterations) is held constant across arms, so feedback quality
is the isolated independent variable. perf_score is normalised by the gold
speedup measured LIVE on this hardware. One CSV row per (scenario, arm, seed,
iteration); a summary row per cell (best perf_score + iters-to-80%).

Env: ACBENCH_LOOP_ITERS (K, default 4), ACBENCH_FEEDBACK_ARMS (comma list to
filter), ACBENCH_MANIFEST (default manifests/perf_real_validated.json),
plus the usual MODEL_ID/ACBENCH_SEEDS/PERF_* from run_experiments.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_experiments as RE          # serve_vllm, wait_health, MODEL_ID, SEEDS, BASE_URL, TEMPERATURE, ...
import run_perf_sweep as PS           # perf_score, extract_diff
import perf_feedback as FB
import perf_profile as PROF

_mpg = importlib.util.spec_from_file_location("mpg", HERE / "measure_perf_go.py")
MPG = importlib.util.module_from_spec(_mpg)
_mpg.loader.exec_module(MPG)          # go_measure, speedup, go_correct, apply_patch, mat

CODE = RE.CODE_DIR
ARTIFACTS = RE.ARTIFACTS
MODEL_ID = RE.MODEL_ID
SEEDS = RE.SEEDS
TEMPERATURE = RE.TEMPERATURE
BASE_URL = RE.BASE_URL
# Ablation: when on, a patch that fails to APPLY is re-prompted WITH the apply error
# (realistic agent loop) and retried, up to APPLY_RETRIES times. Off (default) = the
# original single-shot-per-iteration behavior, so the off-baseline run is unchanged.
APPLY_FB = os.environ.get("ACBENCH_APPLY_FEEDBACK", "0") == "1"
APPLY_RETRIES = int(os.environ.get("ACBENCH_APPLY_RETRIES", "2"))
# F1 CONTROL (reviewer ask): retry the SAME number of times as apply-feedback ON (extra
# resamples) but WITHOUT the specific apply-error text -> isolates "more attempts" from
# "error CONTENT". retry-only ~= off  => lift is content; retry-only ~= on => lift is attempts.
RETRY_ONLY = os.environ.get("ACBENCH_RETRY_ONLY", "0") == "1"
# CONTAMINATION PROBE: persist each emitted model diff to a sidecar JSONL for diff-vs-human-fix overlap.
CAPTURE_PATCHES = os.environ.get("ACBENCH_CAPTURE_PATCHES", "0") == "1"
MANIFEST = os.environ.get("ACBENCH_MANIFEST", "manifests/perf_real_validated.json")
K = int(os.environ.get("ACBENCH_LOOP_ITERS", "4"))
MAX_CHARS = int(os.environ.get("ACBENCH_MAX_PROMPT_CHARS", "55000") or "0")
COUNT = int(os.environ.get("PERF_REPS", "6"))
BENCHTIME = os.environ.get("PERF_BENCHTIME", "1s")
# Dry-run: no model/vLLM — the gold fix stands in for the agent each iteration,
# so the full apply->grade->profile->feedback->CSV path can be validated offline.
DRYRUN = os.environ.get("ACBENCH_LOOP_DRYRUN") == "1"

# arm name -> (fidelity level, modality, misleading?)
ALL_ARMS = [
    ("none", "none", None, False),
    ("directional", "directional", None, False),
    ("numbers", "numbers", None, False),
    ("benchstat", "benchstat", None, False),
    ("prof_cpu", "func_profile", "cpu", False),
    ("prof_alloc", "func_profile", "alloc", False),
    ("prof_line", "line_profile", "combined", False),
    ("misleading", "func_profile", "cpu", True),   # stale base profile
    ("adversarial", "adversarial", "cpu", False),  # real profile, rendered confidently-wrong
]
_want = set(s for s in os.environ.get("ACBENCH_FEEDBACK_ARMS", "").split(",") if s)
ARMS = [a for a in ALL_ARMS if not _want or a[0] in _want]


def log(m: str) -> None:
    print(f"[acbench-perfloop] {m}", flush=True)


def _apply_error_note(prev_diff: str, err: str) -> str:
    """Realistic agent retry: tell the model its diff did not apply + the patch-tool
    error, and ask for a corrected diff. The MODEL self-corrects (not the harness)."""
    return ("Your previous unified diff did NOT apply to the repository. The patch tool reported:\n"
            f"{(err or '').strip()[:800]}\n"
            "Produce a CORRECTED unified diff that applies cleanly to the ACTUAL current file: "
            "use the real surrounding context lines exactly, and do not invent files, paths, or "
            "context. Return ONLY the corrected unified diff.")


def _retry_only_note() -> str:
    """F1 control retry: tell the model to try again but withhold the specific apply error
    (the only difference vs the ON arm), isolating extra-attempts from error content."""
    return ("Your previous unified diff did not apply. Produce another unified diff for the same "
            "task that applies cleanly to the current file. Return ONLY the unified diff.")


def _prompt(file_rel, file_text, pkg, bench, prev_diff, feedback):
    if MAX_CHARS and len(file_text) > MAX_CHARS:
        head = MAX_CHARS * 2 // 3
        file_text = file_text[:head] + "\n... [truncated] ...\n" + file_text[len(file_text) - (MAX_CHARS - head):]
    p = [f"Optimize `{file_rel}` for speed WITHOUT changing behavior.",
         f"Benchmark: go test -bench=^{bench}$ ./{pkg}. Do NOT edit any _test.go file.",
         "Return ONLY a unified diff (git apply format) against the file shown.",
         f"\n--- current file: {file_rel} ---\n{file_text}"]
    if prev_diff:
        p.append(f"\n--- your previous attempt (diff) ---\n{prev_diff}")
    if feedback:
        p.append(f"\n--- result of your previous attempt ---\n{feedback}")
    return "\n".join(p)


def _hotfunc(rows):
    """Hottest non-runtime symbol from pprof -top rows, as a literal `-list` regex."""
    for _, name in rows or []:
        name = re.sub(r"\s+\((?:partial-)?inline\)$", "", name)   # -top display label, not part of the symbol
        if not name.split(".")[0] in ("runtime", "sync", "reflect", "internal"):
            return re.escape(name.split("[")[0])
    return None


def _measure_attempt(cand, pkg, bench, race, base_ns, expert_speedup, best_speedup,
                     level, modality, misleading, base_profiles, base_raw, td):
    """Run the candidate and collect ONLY the artifacts the arm's level needs."""
    a = {"applied": True, "correct": False}
    if not MPG.go_correct(cand, pkg, None):
        return a
    a["correct"] = True
    nums = PROF.bench_numbers(cand, pkg, bench, race, BENCHTIME, COUNT)
    cand_ns = {k: v["ns"] for k, v in nums.items()}
    sp = MPG.speedup(base_ns, cand_ns)
    a["speedup"] = sp
    a["perf_score"] = PS.perf_score(sp, expert_speedup) if sp else 0.0
    a.update(PROF.aggregate(nums))                       # ns, b, allocs
    ref = best_speedup if best_speedup is not None else 1.0   # best correct attempt so far, else the baseline
    a["direction"] = ("faster" if (sp and sp > ref * 1.01)
                      else "slower" if (sp and sp < ref * 0.99) else "same")
    if level == "benchstat":
        cand_raw = PROF.bench_raw(cand, pkg, bench, race, BENCHTIME, COUNT)
        bp = Path(td) / "_b.txt"; cp = Path(td) / "_c.txt"
        bp.write_text(base_raw); cp.write_text(cand_raw)
        a["benchstat"] = PROF.benchstat(cand, str(bp), str(cp))
    elif level in ("func_profile", "line_profile", "adversarial"):
        if misleading:                                  # stale profile from the unoptimised base
            a["cpu_top"], a["alloc_top"], cpu_path, mem_path = base_profiles
        else:                                           # adversarial collects the REAL profile; render_feedback inverts it
            a["cpu_top"], a["alloc_top"], cpu_path, mem_path = PROF.collect_profiles(cand, pkg, bench, race, BENCHTIME)
        if modality in ("escape", "combined") or level == "line_profile":
            tf = TARGET_FILE.get(bench, "")
            a["escape"] = PROF.escape_analysis(cand, pkg, tf) if tf else []
        if level == "line_profile":
            fn = _hotfunc(a.get("alloc_top")) or _hotfunc(a.get("cpu_top"))
            a["pprof_list"] = PROF.pprof_list(cand, mem_path, fn, "alloc_space") if fn else ""
    return a


TARGET_FILE: dict = {}   # bench -> target source file (for escape analysis)


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    # Multi-node serving (e.g. an 8-GPU GLM-5.2 run across 2 NVL4 trays). Two paths:
    #  - vLLM: Ray bootstrap; worker ranks only join Ray so the head's vLLM uses their
    #    GPUs; they never run the loop.
    #  - SGLang (ACBENCH_SERVE_BACKEND=sglang): native torch-distributed; EVERY node
    #    runs launch_server; worker ranks block on it; rank-0 serves the API + runs loop.
    node_rank = int(os.getenv("NODE_RANK") or os.getenv("JOB_COMPLETION_INDEX", "0"))
    backend = RE.SERVE_BACKEND
    srv = None
    if RE.NNODES > 1 and not DRYRUN:
        if backend == "sglang":
            srv = RE.serve_sglang()
            if node_rank != 0:
                srv.wait()
                return
        else:
            os.environ["VLLM_HOST_IP"] = RE.host_ip()
            if shutil.which("ray"):
                subprocess.run(["ray", "stop", "--force"], check=False)
            if node_rank != 0:
                RE.run_worker()
                return
            RE.start_ray_head()
            RE.wait_for_ray_gpus(RE.NNODES * RE.GPUS_PER_NODE)
    if not DRYRUN:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(CODE)], check=True)
    sys.path.insert(0, str(CODE))
    from acbench.models.scenario import ScenarioSpec
    from acbench.executors.local_code import patch_modified_paths, forbidden_path_violations
    from acbench.executors.backends.code.standalone import apply_patch as std_apply
    from acbench.agents.openai_code import OpenAICodePatchAgent
    os.environ.setdefault("OPENAI_API_KEY", "EMPTY")
    # Generate via the robust agent path (same as run_perf_real) so EVERY model gets
    # fair extraction/normalize/validate/repair-retry, not the weak hand-rolled one.
    AGENT = OpenAICodePatchAgent()

    entries = json.loads((CODE / MANIFEST).read_text())["scenarios"]
    raws = [json.loads((CODE / e["scenario"]).read_text()) for e in entries]
    rels = [e["scenario"] for e in entries]

    if DRYRUN:
        vllm = None
    elif srv is not None:
        vllm = srv                        # SGLang head server already launched in MN bootstrap
    elif backend == "sglang":
        vllm = RE.serve_sglang()          # single-node SGLang
    else:
        vllm = RE.serve_vllm()
    rows = []
    patch_rows = []
    out = ARTIFACTS / f"perfloop_{MODEL_ID.split('/')[-1]}.csv"
    fields = ["model", "scenario_id", "arm", "level", "modality", "seed", "iteration",
              "applied", "correct", "measured_speedup", "perf_score", "best_perf_score"]
    try:
        if not DRYRUN:
            RE.wait_health()
        for rawd, rel in zip(raws, rels):
            sid = rawd["scenario_id"]
            perf = rawd["evaluation"]["perf"]
            pkg, bench = perf["pkg"], perf["benchmark"]
            race = "-race" if "-race" in " ".join(rawd["build"].get("test_cmds", [])) else ""
            targets = rawd.get("code_fault", {}).get("target_files", [])
            TARGET_FILE[bench] = targets[0] if targets else ""
            try:
                base = Path(MPG.mat.materialize_one(rel, patch_suffix="bench", require_patch=False))
                # Strip .git so the model-candidate apply uses the LENIENT parser
                # (apply_patch_without_git), matching run_perf_real. With .git present
                # std_apply does a STRICT git apply that rejects every imperfect LLM
                # diff -> applied=0. (Gold still applies: clean diff via git apply sans .git.)
                shutil.rmtree(base / ".git", ignore_errors=True)
                base_nums = PROF.bench_numbers(base, pkg, bench, race, BENCHTIME, COUNT)
                if not base_nums:
                    raise RuntimeError(f"no benchmark results for {bench} at base")
                base_ns = {k: v["ns"] for k, v in base_nums.items()}
                base_agg = PROF.aggregate(base_nums)
            except Exception as exc:  # noqa: BLE001
                log(f"skip {sid}: base setup failed: {exc}")
                continue
            # live gold speedup on THIS hardware (normaliser)
            expert_speedup = perf.get("gold_speedup") or 1.0
            try:
                with tempfile.TemporaryDirectory() as gtd:
                    gc = Path(gtd) / "g"; shutil.copytree(base, gc)
                    if MPG.apply_patch(gc, CODE / "patches" / f"{sid}_fix.diff") and MPG.go_correct(gc, pkg, None):
                        gns = {k: v["ns"] for k, v in PROF.bench_numbers(gc, pkg, bench, race, BENCHTIME, COUNT).items()}
                        live = MPG.speedup(base_ns, gns)
                        if live and live > 1.0:
                            expert_speedup = live
            except Exception as exc:  # noqa: BLE001
                log(f"{sid}: live gold failed, baked {expert_speedup}: {exc}")
            base_raw = PROF.bench_raw(base, pkg, bench, race, BENCHTIME, COUNT)
            base_profiles = PROF.collect_profiles(base, pkg, bench, race, BENCHTIME)  # for the misleading arm
            file_rel = TARGET_FILE[bench]
            file_text = (base / file_rel).read_text(encoding="utf-8", errors="replace") if file_rel else ""
            log(f"{sid}: expert={expert_speedup:.2f}x; arms={[a[0] for a in ARMS]}")

            for arm, level, modality, misleading in ARMS:
                for seed in SEEDS:
                    best_score, best_sp, prev_diff, prev_attempt = 0.0, None, "", None
                    for it in range(1, K + 1):
                        fb = "" if it == 1 else FB.render_feedback(level, modality, prev_attempt, base_agg, expert_speedup, it - 1)
                        forbidden = list(rawd["evaluation"].get("forbidden_paths", []))
                        applied = False
                        with tempfile.TemporaryDirectory() as td:
                            cand = Path(td) / "c"; pf = Path(td) / "d.diff"
                            diff, apply_err = "", ""
                            tries = 1 + (APPLY_RETRIES if ((APPLY_FB or RETRY_ONLY) and not DRYRUN) else 0)
                            for gtry in range(tries):
                                if DRYRUN:
                                    diff = PS.extract_diff((CODE / "patches" / f"{sid}_fix.diff").read_text(encoding="utf-8"))
                                else:
                                    afb = fb
                                    if gtry > 0:  # retry: ON = specific apply error; RETRY_ONLY control = generic note (no error content)
                                        note = _retry_only_note() if RETRY_ONLY else _apply_error_note(diff, apply_err)
                                        afb = ((fb + "\n\n") if fb else "") + note
                                    try:
                                        diff = AGENT.complete_patch(
                                            _prompt(file_rel, file_text, pkg, bench, prev_diff, afb),
                                            model=MODEL_ID, base_url=BASE_URL, api="chat_completions",
                                            temperature=TEMPERATURE, seed=seed + it + 100 * gtry)
                                    except Exception as exc:  # noqa: BLE001 - one failed attempt must not abort the run
                                        log(f"gen fail {sid}/{level}-{modality}/it{it}.{gtry}: {exc}"); diff = ""
                                if cand.exists():
                                    shutil.rmtree(cand)
                                shutil.copytree(base, cand)
                                applied, apply_err = False, ""
                                if diff.strip() and not forbidden_path_violations(patch_modified_paths(diff), forbidden):
                                    pf.write_text(diff); applied, apply_err = std_apply(cand, pf)
                                if applied or DRYRUN:
                                    break
                            if applied:
                                for fp in forbidden:
                                    s, d = base / fp, cand / fp
                                    if s.exists():
                                        d.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(s, d)
                                attempt = _measure_attempt(cand, pkg, bench, race, base_ns, expert_speedup,
                                                           best_sp, level, modality, misleading, base_profiles, base_raw, td)
                            else:
                                attempt = {"applied": False, "correct": False}
                        attempt["applied"] = applied
                        if attempt.get("correct") and attempt.get("perf_score", 0) > best_score:
                            best_score = attempt["perf_score"]
                        # Directional reference: best speedup of ANY correct attempt (perf_score
                        # is 0 below 1.0x, so it cannot track sub-baseline attempts).
                        if attempt.get("correct") and attempt.get("speedup") and (
                                best_sp is None or attempt["speedup"] > best_sp):
                            best_sp = attempt["speedup"]
                        prev_diff = diff   # keep the shown diff in step with the feedback (may be empty)
                        prev_attempt = attempt
                        if CAPTURE_PATCHES and diff.strip():
                            patch_rows.append({"model": MODEL_ID, "scenario_id": sid, "arm": arm,
                                               "seed": seed, "iteration": it, "applied": bool(applied),
                                               "correct": bool(attempt.get("correct", False)),
                                               "perf_score": round(attempt.get("perf_score", 0.0), 3), "diff": diff})
                        rows.append({"model": MODEL_ID, "scenario_id": sid, "arm": arm, "level": level,
                                     "modality": modality or "", "seed": seed, "iteration": it,
                                     "applied": applied, "correct": attempt.get("correct", False),
                                     "measured_speedup": round(attempt["speedup"], 3) if attempt.get("speedup") else None,
                                     "perf_score": round(attempt.get("perf_score", 0.0), 3),
                                     "best_perf_score": round(best_score, 3)})
                    log(f"  {sid}/{arm}/seed{seed}: best perf_score={best_score:.3f}")
                with out.open("w", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
    finally:
        with out.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
        log(f"wrote {out} ({len(rows)} rows)")
        if CAPTURE_PATCHES:
            pout = ARTIFACTS / f"perfloop_patches_{MODEL_ID.split('/')[-1]}.jsonl"
            with pout.open("w") as pfh:
                for pr in patch_rows:
                    pfh.write(json.dumps(pr) + "\n")
            log(f"wrote {pout} ({len(patch_rows)} patches)")
        if vllm and vllm.poll() is None:
            vllm.terminate()
            try:
                vllm.wait(timeout=30)
            except subprocess.TimeoutExpired:
                vllm.kill()


if __name__ == "__main__":
    main()
