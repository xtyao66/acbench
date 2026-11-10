#!/usr/bin/env python3
"""In-job ACBench runner for Volt.

Runs inside a vLLM container on a Volt GB200 job. The head pod serves the model
with vLLM, waits for the API to become healthy, then runs ACBench against the
local OpenAI-compatible endpoint and writes results under ``/volt/artifacts``.

Single-node (NNODES=1) serves vLLM directly; multi-node (NNODES>1) bootstraps a
Ray cluster (head on NODE_RANK 0, workers join) before ``vllm serve``.

Configuration is via environment variables (set in the job YAML command):

  MODEL_ID                served model id (e.g. openai/gpt-oss-20b)
  TENSOR_PARALLEL_SIZE    vLLM --tensor-parallel-size
  PIPELINE_PARALLEL_SIZE  vLLM --pipeline-parallel-size
  MAX_MODEL_LEN           vLLM --max-model-len (ACBench code prompts are large)
  NNODES, GPUS_PER_NODE   cluster topology
  VLLM_PORT, RAY_PORT     ports (default 8000 / 6379)
  ACBENCH_MANIFESTS       comma-separated manifest paths (repo-relative)
  ACBENCH_MAX_STEPS       per-agent max steps (default 6)
  OPENAI_API_KEY          any non-empty string (vLLM ignores unless --api-key)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib import request

CODE_DIR = Path(os.environ.get("ACBENCH_CODE_DIR", "/volt/code"))
ARTIFACTS = Path(os.environ.get("volt_artifacts", os.environ.get("VOLT_ARTIFACTS", "/volt/artifacts")))

MODEL_ID = os.environ.get("MODEL_ID", "openai/gpt-oss-20b")
TP = int(os.environ.get("TENSOR_PARALLEL_SIZE", "4"))
PP = int(os.environ.get("PIPELINE_PARALLEL_SIZE", "1"))
MAX_MODEL_LEN = int(os.environ.get("MAX_MODEL_LEN", "32768"))
NNODES = int(os.environ.get("NNODES", "1"))
GPUS_PER_NODE = int(os.environ.get("GPUS_PER_NODE", str(TP)))
VLLM_PORT = int(os.environ.get("VLLM_PORT", "8000"))
RAY_PORT = int(os.environ.get("RAY_PORT", "6379"))
MAX_STEPS = int(os.environ.get("ACBENCH_MAX_STEPS", "6"))
MANIFESTS = [m.strip() for m in os.environ.get(
    "ACBENCH_MANIFESTS", "manifests/github_openclaw_smoke.json"
).split(",") if m.strip()]
# When set, run each manifest twice (coupled vs --disable-coupling) and report the
# combined-mode delta — the coupling ablation.
ABLATE_COUPLING = os.environ.get("ACBENCH_ABLATE_COUPLING", "0") == "1"
BASE_URL = f"http://127.0.0.1:{VLLM_PORT}/v1"


def log(message: str) -> None:
    print(f"[acbench-volt] {message}", flush=True)


def host_ip() -> str:
    out = subprocess.check_output(["hostname", "-i"], text=True).strip()
    return out.split()[0]


def bootstrap_tokenizer_cache() -> None:
    enc_dir = Path("/tmp/encodings")
    enc_dir.mkdir(parents=True, exist_ok=True)
    for encoding in ("o200k_base.tiktoken", "cl100k_base.tiktoken"):
        target = enc_dir / encoding
        if target.exists():
            continue
        try:
            request.urlretrieve(
                f"https://openaipublic.blob.core.windows.net/encodings/{encoding}", target
            )
        except Exception as exc:  # best-effort; not all models need these
            log(f"tokenizer encoding download failed ({encoding}): {exc}")
    os.environ["TIKTOKEN_ENCODINGS_BASE"] = str(enc_dir)
    os.environ["TIKTOKEN_RS_CACHE_DIR"] = str(enc_dir)


def install_acbench() -> None:
    log(f"installing ACBench from {CODE_DIR}")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(CODE_DIR)], check=True)


def start_ray_head() -> None:
    log("starting Ray head")
    subprocess.run(
        ["ray", "start", "--head", f"--port={RAY_PORT}",
         f"--node-ip-address={host_ip()}", "--dashboard-host=0.0.0.0",
         f"--num-gpus={GPUS_PER_NODE}"],
        check=True,
    )


def start_ray_worker(head_addr: str) -> None:
    address = f"{head_addr}:{RAY_PORT}"
    log(f"joining Ray at {address}")
    for _ in range(120):
        if subprocess.run(
            ["ray", "start", f"--address={address}",
             f"--node-ip-address={host_ip()}", f"--num-gpus={GPUS_PER_NODE}"],
        ).returncode == 0:
            log("Ray worker joined")
            return
        time.sleep(3)
    raise RuntimeError(f"Ray worker failed to join {address}")


def wait_for_ray_gpus(expected: int) -> None:
    import ray

    for _ in range(200):
        try:
            ray.init(address=f"{host_ip()}:{RAY_PORT}")
            gpus = ray.cluster_resources().get("GPU", 0)
            ray.shutdown()
            log(f"Ray GPUs visible: {gpus} / {expected}")
            if gpus >= expected:
                return
        except Exception as exc:
            log(f"Ray not ready: {exc}")
        time.sleep(3)
    raise RuntimeError(f"timed out waiting for Ray to register {expected} GPUs")


def serve_vllm() -> subprocess.Popen:
    cmd = [
        "vllm", "serve", MODEL_ID,
        "--tensor-parallel-size", str(TP),
        "--pipeline-parallel-size", str(PP),
        "--max-model-len", str(MAX_MODEL_LEN),
        "--host", "0.0.0.0", "--port", str(VLLM_PORT),
        "--trust-remote-code",
    ]
    if NNODES > 1:
        cmd += ["--distributed-executor-backend", "ray"]
    log("starting vLLM: " + " ".join(cmd))
    return subprocess.Popen(cmd)


def wait_for_health(timeout_seconds: int = 5400) -> None:
    url = f"http://127.0.0.1:{VLLM_PORT}/health"
    log(f"waiting up to {timeout_seconds}s for vLLM health at {url}")
    start = time.monotonic()
    while time.monotonic() - start < timeout_seconds:
        if subprocess.run(["curl", "-sf", url],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            log("vLLM API is healthy")
            return
        time.sleep(3)
    raise RuntimeError("vLLM did not become healthy in time")


def write_model_predictions(manifest_rel: str, *, disable_coupling: bool = False, label: str = "") -> Path:
    """Build a predictions file routing every scenario to the local endpoint."""

    manifest = json.loads((CODE_DIR / manifest_rel).read_text(encoding="utf-8"))
    defaults = {
        "code_agent_ref": "acbench.agents.openai_code:OpenAICodePatchAgent",
        "aiops_agent_ref": "acbench.agents.openai_ops:OpenAIOpsAgent",
        "openai_model": MODEL_ID,
        "openai_base_url": BASE_URL,
        "openai_api_key_env": "OPENAI_API_KEY",
        "code_agent_config": {"api": "chat_completions"},
        "ops_agent_config": {"api": "chat_completions"},
        "max_steps": MAX_STEPS,
        "disable_coupling": disable_coupling,
    }
    predictions: dict[str, object] = {"_defaults": defaults}
    for entry in manifest["scenarios"]:
        scenario_path = CODE_DIR / entry["scenario"]
        scenario_id = json.loads(scenario_path.read_text(encoding="utf-8"))["scenario_id"]
        predictions[scenario_id] = {}
    stem = Path(manifest_rel).stem + (f"_{label}" if label else "")
    out = Path("/tmp") / f"model_predictions_{stem}.json"
    out.write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    return out


def run_acbench(manifest_rel: str, *, disable_coupling: bool = False, label: str = "") -> dict:
    predictions_path = write_model_predictions(manifest_rel, disable_coupling=disable_coupling, label=label)
    name = Path(manifest_rel).stem + (f"_{label}" if label else "")
    eval_out = ARTIFACTS / f"{name}_eval.json"
    log(f"running ACBench on {manifest_rel} (disable_coupling={disable_coupling}) -> {eval_out}")
    proc = subprocess.run(
        [sys.executable, "-m", "acbench.orchestrator.cli",
         "--manifest", manifest_rel,
         "--predictions", str(predictions_path),
         "--evaluation-output", str(eval_out)],
        cwd=str(CODE_DIR), text=True,
    )
    result = {"manifest": manifest_rel, "returncode": proc.returncode,
              "eval_output": str(eval_out), "disable_coupling": disable_coupling}
    if eval_out.exists():
        data = json.loads(eval_out.read_text(encoding="utf-8"))
        result["submitted"] = data.get("submitted")
        result["success"] = data.get("success")
        result["score_summary"] = data.get("score_summary")
    return result


def combined_metrics(eval_path: Path) -> dict:
    """Aggregate the combined-mode rows of an eval JSON (for the ablation)."""

    if not eval_path.exists():
        return {}
    data = json.loads(eval_path.read_text(encoding="utf-8"))
    rows = [v for v in data.get("results", {}).values() if v.get("mode") == "combined"]
    n = len(rows) or 1

    def _mean(key: str) -> float:
        return round(sum(float(r.get(key, 0.0) or 0.0) for r in rows) / n, 4)

    loc = []
    for row in rows:
        coupling = (row.get("score_breakdown", {}) or {}).get("coupling", {}) or {}
        value = coupling.get("diagnosis_localization_consistent")
        if isinstance(value, bool):
            loc.append(1.0 if value else 0.0)
    return {
        "combined_scenarios": len(rows),
        "combined_success": sum(1 for r in rows if r.get("status") == "success"),
        "mean_final_score": _mean("final_score"),
        "mean_code_score": _mean("code_score"),
        "mean_ops_score": _mean("ops_score"),
        "mean_localization_consistent": round(sum(loc) / len(loc), 4) if loc else None,
    }


def run_head() -> None:
    if NNODES > 1:
        start_ray_head()
        wait_for_ray_gpus(NNODES * GPUS_PER_NODE)

    vllm = serve_vllm()
    summary: dict[str, object] = {"model": MODEL_ID, "base_url": BASE_URL,
                                  "manifests": MANIFESTS, "runs": []}
    try:
        wait_for_health()
        # vLLM accepts any token unless launched with --api-key.
        os.environ.setdefault("OPENAI_API_KEY", "EMPTY")
        for manifest_rel in MANIFESTS:
            try:
                if ABLATE_COUPLING:
                    # Run each manifest twice and compare combined-mode outcomes.
                    coupled = run_acbench(manifest_rel, disable_coupling=False, label="coupled")
                    independent = run_acbench(manifest_rel, disable_coupling=True, label="independent")
                    stem = Path(manifest_rel).stem
                    cm = combined_metrics(ARTIFACTS / f"{stem}_coupled_eval.json")
                    im = combined_metrics(ARTIFACTS / f"{stem}_independent_eval.json")
                    ablation = {
                        "manifest": manifest_rel,
                        "model": MODEL_ID,
                        "coupled": cm,
                        "independent": im,
                        "delta_coupled_minus_independent": {
                            "mean_final_score": round(cm.get("mean_final_score", 0.0) - im.get("mean_final_score", 0.0), 4),
                            "mean_code_score": round(cm.get("mean_code_score", 0.0) - im.get("mean_code_score", 0.0), 4),
                            "mean_ops_score": round(cm.get("mean_ops_score", 0.0) - im.get("mean_ops_score", 0.0), 4),
                            "combined_success": cm.get("combined_success", 0) - im.get("combined_success", 0),
                        },
                    }
                    summary["runs"].append({"coupled": coupled, "independent": independent})
                    summary.setdefault("ablations", []).append(ablation)
                    log(f"COUPLING ABLATION ({manifest_rel}): final coupled={cm.get('mean_final_score')} "
                        f"independent={im.get('mean_final_score')} "
                        f"delta={ablation['delta_coupled_minus_independent']['mean_final_score']}")
                else:
                    summary["runs"].append(run_acbench(manifest_rel))
            except Exception as exc:
                log(f"ACBench run failed for {manifest_rel}: {exc}")
                summary["runs"].append({"manifest": manifest_rel, "error": str(exc)})
    finally:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        (ARTIFACTS / "acbench_volt_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        # Persist the per-run output directories (logs/patches) too.
        runs_dir = CODE_DIR / "runs"
        if runs_dir.exists():
            try:
                subprocess.run(["cp", "-r", str(runs_dir), str(ARTIFACTS / "runs")], check=False)
            except Exception as exc:
                log(f"could not copy runs/: {exc}")
        if vllm.poll() is None:
            vllm.terminate()
            try:
                vllm.wait(timeout=30)
            except subprocess.TimeoutExpired:
                vllm.kill()
        subprocess.run(["ray", "stop", "--force"], check=False)
    log("head finished")


def run_worker() -> None:
    head_addr = os.environ.get("HEAD_ADDRESS") or f"{os.environ.get('JOB_ID', 'job')}-0"
    start_ray_worker(head_addr)
    # Keep the worker alive while the head serves + evaluates.
    while True:
        time.sleep(15)
        try:
            import socket
            with socket.create_connection((head_addr, RAY_PORT), timeout=5):
                continue
        except OSError:
            log("head Ray port unreachable; worker exiting")
            break
    subprocess.run(["ray", "stop", "--force"], check=False)


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    node_rank = int(os.getenv("NODE_RANK") or os.getenv("JOB_COMPLETION_INDEX", "0"))
    log(f"node_rank={node_rank} nnodes={NNODES} model={MODEL_ID} tp={TP} pp={PP} "
        f"max_model_len={MAX_MODEL_LEN} manifests={MANIFESTS}")
    subprocess.run(["nvidia-smi", "-L"], check=False)
    bootstrap_tokenizer_cache()
    install_acbench()
    subprocess.run(["ray", "stop", "--force"], check=False)

    if node_rank == 0:
        run_head()
    else:
        run_worker()


if __name__ == "__main__":
    main()
