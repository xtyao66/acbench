#!/usr/bin/env python3
"""Run configured ACBench manifests with the OpenAI code agent."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from acbench.evaluation.evaluate import evaluate_predictions
from acbench.orchestrator.runner import ACBenchRunner
from acbench.paths import repo_root, resolve_repo_path


def _load_config(config_path: str | Path) -> dict:
    path = resolve_repo_path(config_path)
    return json.loads(path.read_text(encoding="utf-8"))


def _apply_openai_credentials(config: dict) -> str:
    openai = config.get("openai", {})
    env_name = str(openai.get("api_key_env", "OPENAI_API_KEY"))
    api_key = str(openai.get("api_key", ""))
    if api_key:
        os.environ[env_name] = api_key
    if not os.environ.get(env_name, ""):
        raise ValueError(
            f"No API key available. Set `{env_name}` in the environment or fill `openai.api_key` in the config."
        )
    return env_name


def _materialize_predictions(manifest_path: Path, defaults: dict) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runner = ACBenchRunner()
    predictions: dict[str, dict] = {"_defaults": defaults}
    for entry in manifest["scenarios"]:
        scenario = runner.load_scenario(entry["scenario"])
        predictions[scenario.scenario_id] = {}
    return predictions


def run_from_config(config_path: str | Path) -> dict:
    config = _load_config(config_path)
    env_name = _apply_openai_credentials(config)
    openai = config.get("openai", {})
    agent = config.get("agent", {})
    defaults = {
        "aiops_agent_ref": str(
            agent.get("ops_agent_ref", "acbench.agents.openai_ops:OpenAIOpsAgent")
        ),
        "code_agent_ref": str(
            agent.get("code_agent_ref", "acbench.agents.openai_code:OpenAICodePatchAgent")
        ),
        "openai_model": str(openai.get("model", "")),
        "openai_api_key_env": env_name,
        "openai_base_url": str(openai.get("base_url", "")),
        "max_steps": int(agent.get("max_steps", 20)),
        "keep_artifacts": bool(agent.get("keep_artifacts", True)),
    }
    if not defaults["openai_model"]:
        raise ValueError("`openai.model` is required in the config.")

    summary_output = resolve_repo_path(
        config.get("summary_output", "runs/openai_agent_batch_summary.json")
    )
    bundle: dict[str, dict] = {"runs": {}}

    with tempfile.TemporaryDirectory(prefix="acbench-openai-agent-") as temp_dir:
        temp_root = Path(temp_dir)
        for run in config.get("runs", []):
            name = str(run.get("name", "unnamed"))
            manifest_path = resolve_repo_path(run["manifest"])
            output_path = resolve_repo_path(run["output"])
            predictions = _materialize_predictions(manifest_path, defaults)
            predictions_path = temp_root / f"{name}_predictions.json"
            predictions_path.write_text(
                json.dumps(predictions, indent=2),
                encoding="utf-8",
            )
            bundle["runs"][name] = evaluate_predictions(
                manifest_path=manifest_path,
                predictions_path=predictions_path,
                output_path=output_path,
            )

    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ACBench manifests with an OpenAI code agent.")
    parser.add_argument(
        "--config",
        default="configs/openai_direct.local.json",
        help="Path to the local OpenAI batch config JSON.",
    )
    args = parser.parse_args()
    bundle = run_from_config(args.config)
    print(json.dumps(bundle, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
