#!/usr/bin/env python3
"""Diagnostic: capture what a model actually PRODUCES on perf patch-generation, to
explain apply=0. For the first N scenarios: serve the model, run the artifact-saving
agent (generate_patch -> saves the RAW response + extracted patch and RAISES on an
invalid unified diff), then try to apply + `go test`. Classifies each attempt:

  INVALID_DIFF  - model never produced a valid unified diff (after repair retries)
  APPLY_FAIL    - valid diff, but hunks don't match the real file (bad context)
  TEST_FAIL     - applied, but breaks `go test` (behavior changed)
  OK            - applied + tests pass (a usable patch)

Logs the outcome + a raw-output snippet per attempt and saves full artifacts under
/volt/artifacts/diag/<model>/<scenario>/ for offline analysis.
"""
from __future__ import annotations

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
import run_experiments as RE  # serve_vllm, wait_health, MODEL_ID, BASE_URL, TEMPERATURE, ARTIFACTS

_spec = importlib.util.spec_from_file_location("mpg", HERE / "measure_perf_go.py")
MPG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MPG)

CODE = RE.CODE_DIR
MODEL_ID = RE.MODEL_ID
BASE_URL = RE.BASE_URL
TEMPERATURE = RE.TEMPERATURE
ART = RE.ARTIFACTS / "diag" / MODEL_ID.split("/")[-1]
MANIFEST = os.environ.get("ACBENCH_MANIFEST", "manifests/perf_real_validated.json")
NSCEN = int(os.environ.get("ACBENCH_DIAG_NSCEN", "3"))


def log(m: str) -> None:
    print(f"[diag] {m}", flush=True)


def main() -> None:
    subprocess.run("apt-get update -qq && apt-get install -y -qq git gcc curl ca-certificates >/dev/null 2>&1 || true", shell=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(CODE)], check=True)
    sys.path.insert(0, str(CODE))
    from acbench.models.scenario import ScenarioSpec
    from acbench.models.runtime import RunConfig
    from acbench.agents.openai_code import OpenAICodePatchAgent
    os.environ.setdefault("OPENAI_API_KEY", "EMPTY")
    ART.mkdir(parents=True, exist_ok=True)

    man = json.loads((CODE / MANIFEST).read_text(encoding="utf-8"))["scenarios"][:NSCEN]
    log(f"model={MODEL_ID} scenarios={[e['scenario'].split('/')[-1] for e in man]}")
    vllm = RE.serve_vllm()
    rows = []
    try:
        RE.wait_health()
        agent = OpenAICodePatchAgent()
        for e in man:
            rel = e["scenario"]
            d = json.loads((CODE / rel).read_text(encoding="utf-8"))
            sid = d["scenario_id"]
            pkg = d["evaluation"]["perf"]["pkg"]
            s = ScenarioSpec.from_file(CODE / rel)
            rc = RunConfig(openai_model=MODEL_ID, openai_base_url=BASE_URL,
                           openai_api_key_env="OPENAI_API_KEY",
                           code_agent_config={"api": "chat_completions", "temperature": TEMPERATURE, "seed": 0})
            sd = ART / sid
            sd.mkdir(parents=True, exist_ok=True)
            outcome, patch = "?", ""
            try:
                res = agent.generate_patch(s, rc, output_dir=sd)
                patch = res.get("patch_text", "") if isinstance(res, dict) else ""
                outcome = "VALID_DIFF"
            except Exception as exc:  # noqa: BLE001
                outcome = "INVALID_DIFF" if "invalid unified diff" in str(exc).lower() else f"GEN_ERROR:{str(exc)[:80]}"
            rp = sd / "openai_response.txt"
            raw = rp.read_text(encoding="utf-8") if rp.exists() else ""
            applied = correct = False
            if patch.strip():
                base = Path(MPG.mat.materialize_one(rel, patch_suffix="bench", require_patch=False))
                with tempfile.TemporaryDirectory() as td:
                    cand = Path(td) / "c"
                    shutil.copytree(base, cand)
                    pf = Path(td) / "p.diff"
                    pf.write_text(patch, encoding="utf-8")
                    applied = MPG.apply_patch(cand, pf)
                    if applied:
                        correct = MPG.go_correct(cand, pkg, None)
                if outcome == "VALID_DIFF":
                    outcome = "OK" if (applied and correct) else ("APPLY_FAIL" if not applied else "TEST_FAIL")
            row = {"model": MODEL_ID, "scenario": sid, "outcome": outcome,
                   "raw_chars": len(raw), "patch_chars": len(patch), "applied": applied, "correct": correct}
            rows.append(row)
            log(f"{sid}: {outcome} raw_chars={len(raw)} patch_chars={len(patch)} applied={applied} correct={correct}")
            log(f"  RAW HEAD: {raw[:700].replace(chr(10), ' / ')}")
            log(f"  PATCH HEAD: {patch[:300].replace(chr(10), ' / ')}")
    finally:
        (ART / "diag_summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        if vllm and vllm.poll() is None:
            vllm.terminate()
            try:
                vllm.wait(timeout=30)
            except subprocess.TimeoutExpired:
                vllm.kill()
    log("=== DIAG SUMMARY ===")
    for r in rows:
        log(f"  {r['scenario']}: {r['outcome']} (patch_chars={r['patch_chars']}, applied={r['applied']}, correct={r['correct']})")


if __name__ == "__main__":
    main()
