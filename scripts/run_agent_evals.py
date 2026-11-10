#!/usr/bin/env python3
"""Run configured ACBench manifests with one generic agent profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from acbench.evaluation.evaluate import evaluate_predictions
from acbench.orchestrator.runner import ACBenchRunner
from acbench.paths import resolve_repo_path


def _materialize_predictions(
    manifest_path: Path,
    *,
    agent_config: str,
    max_steps: int,
    keep_artifacts: bool,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runner = ACBenchRunner()
    predictions: dict[str, dict] = {
        "_defaults": {
            "agent_config": agent_config,
            "max_steps": max_steps,
            "keep_artifacts": keep_artifacts,
        }
    }
    for entry in manifest["scenarios"]:
        scenario = runner.load_scenario(entry["scenario"])
        predictions[scenario.scenario_id] = {}
    return predictions


def run_batch(
    *,
    agent_config: str,
    local_manifest: str,
    github_manifest: str,
    local_output: str,
    github_output: str,
    summary_output: str,
    max_steps: int,
    keep_artifacts: bool,
) -> dict:
    agent_config_path = str(resolve_repo_path(agent_config))
    summary: dict[str, dict] = {"runs": {}}

    with tempfile.TemporaryDirectory(prefix="acbench-agent-batch-") as temp_dir:
        temp_root = Path(temp_dir)
        for name, manifest, output in (
            ("local", local_manifest, local_output),
            ("github", github_manifest, github_output),
        ):
            manifest_path = resolve_repo_path(manifest)
            output_path = resolve_repo_path(output)
            predictions = _materialize_predictions(
                manifest_path,
                agent_config=agent_config_path,
                max_steps=max_steps,
                keep_artifacts=keep_artifacts,
            )
            predictions_path = temp_root / f"{name}_predictions.json"
            predictions_path.write_text(
                json.dumps(predictions, indent=2),
                encoding="utf-8",
            )
            summary["runs"][name] = evaluate_predictions(
                manifest_path=manifest_path,
                predictions_path=predictions_path,
                output_path=output_path,
            )

    summary_path = resolve_repo_path(summary_output)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run ACBench with one generic agent profile."
    )
    parser.add_argument(
        "--agent-config",
        required=True,
        help="Path to one generic agent profile JSON.",
    )
    parser.add_argument(
        "--local-manifest",
        default="manifests/local_suite.json",
        help="Manifest for local scenarios.",
    )
    parser.add_argument(
        "--github-manifest",
        default="manifests/github_openclaw_extended.json",
        help="Manifest for GitHub-derived scenarios.",
    )
    parser.add_argument(
        "--local-output",
        default="",
        help="Output JSON for the local suite (default: runs/local_agent_eval_<profile>.json).",
    )
    parser.add_argument(
        "--github-output",
        default="",
        help="Output JSON for the GitHub suite (default: runs/github_agent_eval_<profile>.json).",
    )
    parser.add_argument(
        "--summary-output",
        default="",
        help="Summary JSON for the combined batch (default: runs/agent_batch_summary_<profile>.json).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=25,
        help="Maximum reserved steps per scenario.",
    )
    parser.add_argument(
        "--keep-artifacts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep run artifacts on disk (disable with --no-keep-artifacts).",
    )
    return parser


def default_output(name: str, agent_config: str) -> str:
    """Default output path, keyed by profile so runs of different profiles never overwrite each other."""

    return f"runs/{name}_{Path(agent_config).stem}.json"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_batch(
        agent_config=args.agent_config,
        local_manifest=args.local_manifest,
        github_manifest=args.github_manifest,
        local_output=args.local_output or default_output("local_agent_eval", args.agent_config),
        github_output=args.github_output or default_output("github_agent_eval", args.agent_config),
        summary_output=(
            args.summary_output or default_output("agent_batch_summary", args.agent_config)
        ),
        max_steps=args.max_steps,
        keep_artifacts=args.keep_artifacts,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
