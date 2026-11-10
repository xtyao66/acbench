#!/usr/bin/env python3
"""In-job experiment sweep for the ACBench coupling study.

Serves the model with vLLM, then for each combined scenario x condition x seed
runs the CODE-repair stage with a chosen diagnosis injected (none/gold/model/
wrong/filler/component) and the fault location revealed or hidden, grades it with
ACBench's real executor + scorecard, and writes one tidy CSV row. The CSV feeds
the cross-model statistics (E1 interaction, E2 quality gradient, E3 components,
E4 leakage, E6 difficulty).

Env: MODEL_ID, TENSOR_PARALLEL_SIZE, MAX_MODEL_LEN, VLLM_PORT, ACBENCH_SEEDS,
ACBENCH_TEMPERATURE, ACBENCH_MANIFEST (default manifests/combined_all.json).
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CODE_DIR = Path(os.environ.get("ACBENCH_CODE_DIR", "/volt/code"))
ARTIFACTS = Path(os.environ.get("volt_artifacts", os.environ.get("VOLT_ARTIFACTS", "/volt/artifacts")))
MODEL_ID = os.environ.get("MODEL_ID", "openai/gpt-oss-20b")
TP = int(os.environ.get("TENSOR_PARALLEL_SIZE", "4"))
MAX_MODEL_LEN = int(os.environ.get("MAX_MODEL_LEN", "32768"))
VLLM_PORT = int(os.environ.get("VLLM_PORT", "8000"))
NNODES = int(os.environ.get("NNODES", "1"))
GPUS_PER_NODE = int(os.environ.get("GPUS_PER_NODE", str(TP)))
PP = int(os.environ.get("PIPELINE_PARALLEL_SIZE", "1"))
RAY_PORT = int(os.environ.get("RAY_PORT", "6379"))
SERVE_BACKEND = os.environ.get("ACBENCH_SERVE_BACKEND", "vllm").strip().lower()  # vllm | sglang
SEEDS = [int(s) for s in os.environ.get("ACBENCH_SEEDS", "0,1,2").split(",") if s.strip()]
TEMPERATURE = float(os.environ.get("ACBENCH_TEMPERATURE", "0.7"))
MANIFEST = os.environ.get("ACBENCH_MANIFEST", "manifests/combined_all.json")
BASE_URL = f"http://127.0.0.1:{VLLM_PORT}/v1"

FILLER = ("Note: routine operational context. Standard monitoring dashboards, on-call rotations, "
          "and alerting thresholds are in place; capacity planning and incident runbooks are reviewed "
          "regularly; logging and tracing are enabled across services for general observability.") * 2

# (name, hide_location, diag_kind)
CONDITIONS = [
    ("E2_none_shown", False, "none"),
    ("E2_gold_shown", False, "gold"),
    ("E2_model_shown", False, "model"),
    ("E2_wrong_shown", False, "wrong"),
    ("E2_filler_shown", False, "filler"),
    ("E1_none_hidden", True, "none"),
    ("E1_model_hidden", True, "model"),
    ("E3_summary_shown", False, "comp_summary"),
    ("E3_rootcause_shown", False, "comp_root_cause"),
    ("E3_remediation_shown", False, "comp_remediation"),
    # n=all-scenarios leakage control: a CORRECT gold diagnosis with the faulty
    # filename scrubbed (the per-scenario gold-leak split only yields n=2).
    ("E4_goldnoleak_shown", False, "gold_noleak"),
]

# Optional subset filter (comma-separated condition NAMES) for cheap focused re-runs.
_only = {c.strip() for c in os.environ.get("ACBENCH_CONDITIONS", "").split(",") if c.strip()}
if _only:
    CONDITIONS = [c for c in CONDITIONS if c[0] in _only]


def log(m: str) -> None:
    print(f"[acbench-exp] {m}", flush=True)


def host_ip() -> str:
    return subprocess.check_output(["hostname", "-i"], text=True).strip().split()[0]


def start_ray_head() -> None:
    log("starting Ray head")
    subprocess.run(["ray", "start", "--head", f"--port={RAY_PORT}",
                    f"--node-ip-address={host_ip()}", "--dashboard-host=0.0.0.0",
                    f"--num-gpus={GPUS_PER_NODE}"], check=True)


def wait_for_ray_gpus(expected: int) -> None:
    import ray
    # 1200*3s = 60min. Multi-node jobs pre-stage weights independently per node, so the
    # head finishes its download well before a slower/contended worker finishes its own
    # copy and joins Ray. The old 200 (10min) times out on a slow-but-healthy worker
    # while it's still downloading (caused V4-Pro-B "timed out waiting for Ray GPUs").
    for _ in range(1200):
        try:
            ray.init(address=f"{host_ip()}:{RAY_PORT}")
            gpus = ray.cluster_resources().get("GPU", 0)
            ray.shutdown()
            log(f"Ray GPUs: {gpus}/{expected}")
            if gpus >= expected:
                return
        except Exception as exc:
            log(f"ray not ready: {exc}")
        time.sleep(3)
    raise RuntimeError("timed out waiting for Ray GPUs")


def run_worker() -> None:
    import socket
    jid = os.environ.get("JOB_ID", "job")
    head = os.environ.get("HEAD_ADDRESS") or f"{jid}-0.volt-{jid}"
    log(f"worker(rank!=0): head={head} port={RAY_PORT} my_ip={host_ip()}")
    # The head's DNS name is not resolvable immediately; wait for it before joining
    # (matches the proven Volt multi-node reference) or `ray start` fails fast.
    resolved = False
    for attempt in range(180):
        try:
            ip = socket.getaddrinfo(head, None)[0][4][0]
            log(f"head DNS resolved -> {ip} (attempt {attempt})")
            resolved = True
            break
        except socket.gaierror as exc:
            if attempt % 10 == 0:
                log(f"head DNS not ready (attempt {attempt}): {exc}")
            time.sleep(2)
    if not resolved:
        log("ERROR: head DNS never resolved")
    log(f"worker joining Ray at {head}:{RAY_PORT}")
    joined = False
    for attempt in range(180):
        r = subprocess.run(["ray", "start", f"--address={head}:{RAY_PORT}",
                            f"--node-ip-address={host_ip()}", f"--num-gpus={GPUS_PER_NODE}"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            joined = True
            log(f"worker joined Ray head (attempt {attempt})")
            break
        if attempt % 5 == 0:
            log(f"join attempt {attempt} failed: {(r.stderr or '').strip()[-200:]}")
        time.sleep(3)
    if not joined:
        log("ERROR: worker never joined Ray head")
    while True:
        time.sleep(15)
        try:
            with socket.create_connection((head, RAY_PORT), timeout=5):
                continue
        except OSError:
            break
    subprocess.run(["ray", "stop", "--force"], check=False)


def serve_vllm() -> subprocess.Popen:
    cmd = ["vllm", "serve", MODEL_ID,
           "--tensor-parallel-size", str(TP),
           "--max-model-len", str(MAX_MODEL_LEN),
           "--host", "0.0.0.0", "--port", str(VLLM_PORT), "--trust-remote-code"]
    if NNODES > 1:
        cmd += ["--pipeline-parallel-size", str(PP), "--distributed-executor-backend", "ray"]
    extra = os.environ.get("VLLM_EXTRA_ARGS", "").strip()
    if extra:
        cmd += extra.split()
    log("serving: " + " ".join(cmd))
    return subprocess.Popen(cmd)


def _resolve_head(head: str, attempts: int = 180) -> None:
    """Block until the head node's DNS name resolves (Volt assigns it lazily)."""
    import socket
    for attempt in range(attempts):
        try:
            ip = socket.getaddrinfo(head, None)[0][4][0]
            log(f"head DNS resolved -> {ip} (attempt {attempt})")
            return
        except socket.gaierror:
            if attempt % 10 == 0:
                log(f"head DNS not ready (attempt {attempt})")
            time.sleep(2)
    log("WARNING: head DNS never resolved")


def serve_sglang() -> subprocess.Popen:
    """Launch SGLang's OpenAI-compatible server -- alt runtime for MoE giants
    (GLM-5.2 / DeepSeek-V4) where vLLM's NvFp4 FLASHINFER_TRTLLM MoE backend hangs.
    Multi-node uses SGLang's NATIVE torch-distributed (--nnodes/--node-rank/
    --dist-init-addr), NOT Ray: every node runs this; the rank-0 node serves the
    HTTP API on VLLM_PORT and --tp-size is GLOBAL (TP x NNODES). Health endpoint
    (/health) and the OpenAI /v1 API are the same as vLLM, so wait_health/BASE_URL
    are reused unchanged. --served-model-name = MODEL_ID so the chat API name matches."""
    node_rank = int(os.getenv("NODE_RANK") or os.getenv("JOB_COMPLETION_INDEX", "0"))
    total_tp = TP * NNODES if NNODES > 1 else TP
    cmd = ["python3", "-m", "sglang.launch_server",
           "--model-path", MODEL_ID, "--served-model-name", MODEL_ID,
           "--tp-size", str(total_tp),
           "--context-length", str(MAX_MODEL_LEN),
           "--host", "0.0.0.0", "--port", str(VLLM_PORT), "--trust-remote-code"]
    if NNODES > 1:
        jid = os.environ.get("JOB_ID", "job")
        head = os.environ.get("HEAD_ADDRESS") or f"{jid}-0.volt-{jid}"
        if node_rank != 0:
            _resolve_head(head)
        cmd += ["--nnodes", str(NNODES), "--node-rank", str(node_rank),
                "--dist-init-addr", f"{head}:{RAY_PORT}"]
    extra = os.environ.get("SGLANG_EXTRA_ARGS", "").strip()
    if extra:
        cmd += extra.split()
    log("serving (sglang): " + " ".join(cmd))
    return subprocess.Popen(cmd)


def serve():
    """Backend dispatcher (vllm | sglang via SERVE_BACKEND). NOTE: the run_experiments
    / run_perf_sweep / run_perf_real mains only wire the vLLM+Ray multi-node bootstrap,
    so SGLang here is SINGLE-NODE only -- multi-node SGLang (native torch-distributed)
    is handled by run_perf_loop.py. Default is vllm, so existing runs are unchanged."""
    if SERVE_BACKEND == "sglang":
        if NNODES > 1:
            raise NotImplementedError(
                "multi-node SGLang is only wired in run_perf_loop.py; set NNODES=1 here "
                "or use the perf-loop runner.")
        return serve_sglang()
    return serve_vllm()


def wait_health(timeout: int | None = None) -> None:
    if timeout is None:
        timeout = int(os.environ.get("ACBENCH_HEALTH_TIMEOUT", "5400"))
    url = f"http://127.0.0.1:{VLLM_PORT}/health"
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if subprocess.run(["curl", "-sf", url], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            log(f"{SERVE_BACKEND} healthy")
            return
        time.sleep(3)
    raise RuntimeError(f"{SERVE_BACKEND} did not become healthy")


def gold_diag(problem) -> dict:
    return {
        "detected": True, "localized": True, "repaired": True,
        "summary": "incident " + ", ".join(problem.detection_keywords),
        "root_cause": "root cause " + ", ".join(problem.localization_keywords),
        "remediation": "fix " + ", ".join(problem.repair_keywords),
        "evidence": list(problem.detection_keywords),
    }


def component_diag(problem, field: str) -> dict:
    base = {"detected": True, "localized": True, "repaired": True,
            "summary": "", "root_cause": "", "remediation": "", "evidence": []}
    if field == "summary":
        base["summary"] = "incident " + ", ".join(problem.detection_keywords)
    elif field == "root_cause":
        base["root_cause"] = "root cause " + ", ".join(problem.localization_keywords)
    elif field == "remediation":
        base["remediation"] = "fix " + ", ".join(problem.repair_keywords)
    return base


def filler_diag() -> dict:
    return {"detected": True, "localized": True, "repaired": True,
            "summary": FILLER, "root_cause": FILLER, "remediation": FILLER, "evidence": [FILLER]}


def gold_leaks_target(scenario, gold) -> bool:
    targets = [Path(t).stem.lower() for t in (scenario.code_fault.target_files or [])] if scenario.code_fault else []
    text = " ".join(str(gold.get(k, "")) for k in ("summary", "root_cause", "remediation")).lower()
    return any(stem and stem in text for stem in targets)


import re as _re


def gold_noleak_diag(gold: dict, scenario) -> dict:
    """A CORRECT gold diagnosis with the faulty FILE name stems scrubbed, so it
    never names the target file. Gives a non-leaking gold control on EVERY
    scenario; the per-scenario gold-leak split (gold_diag_leaks_target) only
    yields n=2 non-leaking scenarios, too thin to defend the headline."""
    if not gold:
        return gold
    stems = [Path(t).stem for t in (scenario.code_fault.target_files or [])] if scenario.code_fault else []
    stems = [s for s in stems if s]

    def scrub(v):
        if isinstance(v, list):
            return [scrub(x) for x in v]
        out = str(v)
        for stem in stems:
            out = _re.sub(rf"\b{_re.escape(stem)}\b", "the affected component", out, flags=_re.IGNORECASE)
        return out

    return {k: scrub(v) for k, v in gold.items()}


def load_authored(sid: str):
    """Load re-authored {gold, wrong} diagnoses for a scenario if present.

    These are leak-free, pre-fix-authored diagnoses (function/module-level root
    cause that does NOT name the fix construct; a per-scenario HARD wrong) stored
    at tasks/diagnoses/<sid>.json and validated by scripts/check_diagnosis_leakage.py.
    When present they OVERRIDE the keyword-derived gold and the neighbor wrong.
    Returns {"gold": dict, "wrong": dict} or None.
    """
    p = CODE_DIR / os.environ.get("ACBENCH_DIAGNOSES_DIR", "tasks/diagnoses") / f"{sid}.json"
    if not p.exists():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log(f"authored-diag load failed {sid}: {exc}")
        return None
    out = {}
    for key in ("gold", "wrong"):
        d = obj.get(key)
        if isinstance(d, dict):
            out[key] = {"detected": True, "localized": True, "repaired": True, **d}
    return out or None


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    node_rank = int(os.getenv("NODE_RANK") or os.getenv("JOB_COMPLETION_INDEX", "0"))
    if NNODES > 1:
        # vLLM needs each node's own IP for cross-node Ray coordination.
        os.environ["VLLM_HOST_IP"] = host_ip()
    if NNODES > 1 and shutil.which("ray"):
        subprocess.run(["ray", "stop", "--force"], check=False)
    if node_rank != 0:
        # Worker nodes only join Ray so the head's vLLM can use their GPUs.
        run_worker()
        return
    if NNODES > 1:
        start_ray_head()
        wait_for_ray_gpus(NNODES * GPUS_PER_NODE)

    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(CODE_DIR)], check=True)
    sys.path.insert(0, str(CODE_DIR))

    from acbench.models.scenario import ScenarioSpec
    from acbench.models.runtime import RunConfig
    from acbench.models.result import BenchmarkResult
    from acbench.executors.local_code import LocalCodeExecutor
    from acbench.executors.backends.ops.runtime import NativeOpsProblem
    from acbench.agents.openai_ops import OpenAIOpsAgent
    from acbench.scoring import build_scorecard

    os.environ.setdefault("OPENAI_API_KEY", "EMPTY")
    manifest = json.loads((CODE_DIR / MANIFEST).read_text(encoding="utf-8"))
    scenarios = [ScenarioSpec.from_file(CODE_DIR / e["scenario"]) for e in manifest["scenarios"]]
    log(f"{len(scenarios)} scenarios x {len(CONDITIONS)} conditions x {len(SEEDS)} seeds")

    vllm = serve()
    rows: list[dict] = []
    out_csv = ARTIFACTS / f"experiments_{MODEL_ID.split('/')[-1]}{os.environ.get('ACBENCH_RUN_TAG', '')}.csv"
    fields = ["model", "scenario_id", "mode", "difficulty", "condition", "diag_kind",
              "hide_location", "seed", "code_score", "final_score", "resolved",
              "f2p_success", "f2p_total", "apply_success", "gold_diag_leaks_target",
              "diag_source", "modified_files", "touched_target", "error"]
    # true target file stems per scenario (for the manipulation check: did the
    # model's patch edit WHERE the bug actually is?)
    _tgt_stems = {}
    for sc in scenarios:
        _tgt_stems[sc.scenario_id] = [Path(t).stem.lower()
                                      for t in ((sc.code_fault.target_files or []) if sc.code_fault else [])]
    try:
        wait_health()
        for scenario in scenarios:
            problem = NativeOpsProblem.from_scenario(scenario) if scenario.ops_fault else None
            gold = gold_diag(problem) if problem else {}
            leak = gold_leaks_target(scenario, gold) if gold else False
            wrong_src = scenarios[(scenarios.index(scenario) + 1) % len(scenarios)]
            wrong = gold_diag(NativeOpsProblem.from_scenario(wrong_src)) if wrong_src.ops_fault else {}
            # Re-authored, leak-free diagnoses (the validity fix) override the
            # keyword-derived gold + neighbor wrong when available.
            diag_source = "derived"
            authored = load_authored(scenario.scenario_id)
            if authored:
                if authored.get("gold"):
                    gold = authored["gold"]
                if authored.get("wrong"):
                    wrong = authored["wrong"]
                leak = gold_leaks_target(scenario, gold) if gold else False
                diag_source = "authored"
            model_diag = None  # computed lazily once

            for cond_name, hide, kind in CONDITIONS:
                for seed in SEEDS:
                    if kind == "none":
                        diag = None
                    elif kind == "gold":
                        diag = gold
                    elif kind == "gold_noleak":
                        diag = gold_noleak_diag(gold, scenario)
                    elif kind == "wrong":
                        diag = wrong
                    elif kind == "filler":
                        diag = filler_diag()
                    elif kind.startswith("comp_"):
                        diag = component_diag(problem, kind[len("comp_"):])
                    elif kind == "model":
                        if model_diag is None and problem is not None:
                            try:
                                agent = OpenAIOpsAgent()
                                agent.configure(RunConfig(openai_model=MODEL_ID, openai_base_url=BASE_URL,
                                                          ops_agent_config={"api": "chat_completions"}))
                                td = ARTIFACTS / "_tmp_ops"; td.mkdir(parents=True, exist_ok=True)
                                model_diag = agent.analyze(problem, output_dir=td).get("assessment", {})
                            except Exception as exc:
                                log(f"model-diag failed {scenario.scenario_id}: {exc}")
                                model_diag = {}
                        diag = model_diag
                    else:
                        diag = None

                    rc = RunConfig(
                        code_agent_ref="acbench.agents.openai_code:OpenAICodePatchAgent",
                        openai_model=MODEL_ID, openai_base_url=BASE_URL, openai_api_key_env="OPENAI_API_KEY",
                        code_agent_config={"api": "chat_completions", "temperature": TEMPERATURE, "seed": seed},
                        upstream_ops_diagnosis=diag,
                        hide_fault_location=hide,
                    )
                    run_dir = ARTIFACTS / "_runs" / f"{scenario.scenario_id}_{cond_name}_{seed}"
                    run_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        cr = LocalCodeExecutor().execute(scenario, run_dir, rc)
                        result = BenchmarkResult(scenario_id=scenario.scenario_id, title=scenario.title, mode=scenario.mode)
                        result.code_result = cr
                        card = build_scorecard(scenario, result)
                        mpaths = cr.details.get("modified_paths", []) or []
                        tstems = _tgt_stems.get(scenario.scenario_id, [])
                        touched = any(Path(p).stem.lower() in tstems for p in mpaths)
                        rows.append({
                            "model": MODEL_ID, "scenario_id": scenario.scenario_id, "mode": scenario.mode,
                            "difficulty": scenario.metadata.difficulty or "unknown",
                            "condition": cond_name, "diag_kind": kind, "hide_location": hide, "seed": seed,
                            "code_score": card.get("code_score"), "final_score": card.get("final_score"),
                            "resolved": bool(cr.build_success and cr.test_success),
                            "f2p_success": len(cr.fail_to_pass_success),
                            "f2p_total": len(scenario.evaluation.fail_to_pass),
                            "apply_success": cr.details.get("apply_success"),
                            "gold_diag_leaks_target": leak,
                            "diag_source": diag_source,
                            "modified_files": ";".join(mpaths),
                            "touched_target": touched,
                            "error": "",
                        })
                    except Exception as exc:
                        log(f"FAILED {scenario.scenario_id}/{cond_name}/{seed}: {exc}")
                        # Record the failed run (e.g. no valid diff after retries, context
                        # overflow) as a 0-score row; dropping it would bias means upward.
                        rows.append({
                            "model": MODEL_ID, "scenario_id": scenario.scenario_id, "mode": scenario.mode,
                            "difficulty": scenario.metadata.difficulty or "unknown",
                            "condition": cond_name, "diag_kind": kind, "hide_location": hide, "seed": seed,
                            "code_score": 0.0, "final_score": 0.0, "resolved": False,
                            "f2p_success": 0, "f2p_total": len(scenario.evaluation.fail_to_pass),
                            "apply_success": False, "gold_diag_leaks_target": leak,
                            "diag_source": diag_source, "modified_files": "", "touched_target": False,
                            "error": f"{type(exc).__name__}: {exc}"[:500],
                        })
                    # free the per-run workspace copy immediately (real Go repos are large)
                    shutil.rmtree(run_dir, ignore_errors=True)
            # flush after each scenario
            with out_csv.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
            log(f"done {scenario.scenario_id} ({len(rows)} rows)")
    finally:
        with out_csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
        log(f"wrote {out_csv} ({len(rows)} rows)")
        # cleanup heavy run dirs; keep only the CSV
        subprocess.run(["rm", "-rf", str(ARTIFACTS / "_runs"), str(ARTIFACTS / "_tmp_ops")], check=False)
        if vllm.poll() is None:
            vllm.terminate()
            try:
                vllm.wait(timeout=30)
            except subprocess.TimeoutExpired:
                vllm.kill()
        if NNODES > 1 and shutil.which("ray"):
            subprocess.run(["ray", "stop", "--force"], check=False)


if __name__ == "__main__":
    main()
