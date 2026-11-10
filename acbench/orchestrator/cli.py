"""Command-line entrypoint for standalone ACBench."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acbench.evaluation.evaluate import evaluate_predictions
from acbench.agents.profile import load_and_resolve_agent_profile
from acbench.evaluation.report import (
    write_markdown_report_from_json,
    write_run_markdown_report,
)
from acbench.orchestrator.demo import run_local_demo
from acbench.orchestrator.doctor import (
    build_readiness_bundle,
    inspect_acbench_code_backend,
)
from acbench.orchestrator.export import (
    export_code_instance,
)
from acbench.orchestrator.runner import ACBenchRunner
from acbench.orchestrator.validate import check_scenario_readiness
from acbench.models.runtime import RunConfig


OPENAI_COMPATIBLE_PROVIDERS = {"openai", "azure_openai", "openai_compatible"}


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""

    parser = argparse.ArgumentParser(description="Run an ACBench scenario.")
    parser.add_argument(
        "--scenario",
        help="Path to a scenario JSON file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use safe dry-run executors instead of live backends.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Maximum steps reserved for future live backends (default: 10).",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Print backend preflight diagnostics and exit.",
    )
    parser.add_argument(
        "--validate-scenario",
        action="store_true",
        help="Validate and print the normalized scenario without executing it.",
    )
    parser.add_argument(
        "--check-readiness",
        action="store_true",
        help="Check whether the scenario is runnable in the current environment.",
    )
    parser.add_argument(
        "--agent-config",
        default="",
        help="Path to a generic agent profile JSON.",
    )
    parser.add_argument(
        "--code-agent-ref",
        default="",
        help="Live code agent class in `module:Class` format.",
    )
    parser.add_argument(
        "--aiops-agent-ref",
        default="",
        help="Live ops agent class in `module:Class` format.",
    )
    parser.add_argument(
        "--code-patch",
        default="",
        help="Optional patch file to apply for local code execution.",
    )
    parser.add_argument(
        "--openai-model",
        default="",
        help="OpenAI model name used by API-backed benchmark agents.",
    )
    parser.add_argument(
        "--openai-api-key-env",
        default="",
        help="Environment variable name that stores the OpenAI API key.",
    )
    parser.add_argument(
        "--openai-base-url",
        default="",
        help="Optional OpenAI-compatible base URL for custom providers.",
    )
    parser.add_argument(
        "--anthropic-model",
        default="",
        help="Anthropic model name used by Claude-backed benchmark agents.",
    )
    parser.add_argument(
        "--anthropic-api-key-env",
        default="",
        help="Environment variable name that stores the Anthropic API key.",
    )
    parser.add_argument(
        "--anthropic-base-url",
        default="",
        help="Anthropic API base URL.",
    )
    parser.add_argument(
        "--anthropic-version",
        default="",
        help="Anthropic API version header.",
    )
    parser.add_argument(
        "--manifest",
        default="",
        help=(
            "Path to a manifest JSON for batch prediction evaluation. Run flags given "
            "with it (e.g. --dry-run, --disable-coupling, agent and model flags) "
            "override the predictions file."
        ),
    )
    parser.add_argument(
        "--predictions",
        default="",
        help="Path to a predictions JSON file for batch evaluation.",
    )
    parser.add_argument(
        "--evaluation-output",
        default="",
        help="Where to write batch evaluation output JSON.",
    )
    parser.add_argument(
        "--export-code-instance",
        default="",
        help="Write a code instance JSON for the given scenario.",
    )
    parser.add_argument(
        "--write-readiness-report",
        default="",
        help="Write a combined backend readiness report JSON and exit.",
    )
    parser.add_argument(
        "--write-markdown-report",
        default="",
        help="Write a markdown report from an evaluation JSON file.",
    )
    parser.add_argument(
        "--evaluation-json",
        default="",
        help="Evaluation JSON input used with --write-markdown-report.",
    )
    parser.add_argument(
        "--write-run-markdown-report",
        default="",
        help="Write a markdown report from one benchmark run directory.",
    )
    parser.add_argument(
        "--run-dir",
        default="",
        help="Run directory used with --write-run-markdown-report.",
    )
    parser.add_argument(
        "--run-local-demo",
        default="",
        help="Run the local gold suite demo and write outputs into the given directory.",
    )
    parser.add_argument(
        "--allow-synthetic-ops",
        action="store_true",
        help=(
            "Opt into the synthetic ops placeholder when no ops agent is configured. "
            "Without this, no-agent ops stages are reported as not evaluated (no credit)."
        ),
    )
    parser.add_argument(
        "--disable-coupling",
        action="store_true",
        help=(
            "Ablation: do NOT thread the ops diagnosis into the code stage for combined "
            "scenarios (run the two stages independently). Used to measure the coupling's effect."
        ),
    )
    return parser


def run_doctor() -> int:
    """Print backend diagnostics."""

    acbench_code_report = inspect_acbench_code_backend()
    print(
        json.dumps(
            {
                "acbench_code": {
                    **acbench_code_report.to_dict(),
                },
            },
            indent=2,
        )
    )
    return 0


def _apply_provider_overrides(run_config: RunConfig, args: argparse.Namespace) -> None:
    """Apply CLI-supplied provider overrides to profile-backed config sections."""

    for section in (run_config.code_agent_config, run_config.ops_agent_config):
        provider = str(section.get("provider", "")).strip().lower()
        if provider in OPENAI_COMPATIBLE_PROVIDERS:
            if args.openai_model:
                section["model"] = args.openai_model
            if args.openai_api_key_env:
                section["api_key_env"] = args.openai_api_key_env
            if args.openai_base_url:
                section["base_url"] = args.openai_base_url
        if provider == "anthropic":
            if args.anthropic_model:
                section["model"] = args.anthropic_model
            if args.anthropic_api_key_env:
                section["api_key_env"] = args.anthropic_api_key_env
            if args.anthropic_base_url:
                section["base_url"] = args.anthropic_base_url
            if args.anthropic_version:
                section["version"] = args.anthropic_version


_PROVIDER_FLAG_FIELDS = (
    "openai_model",
    "openai_api_key_env",
    "openai_base_url",
    "anthropic_model",
    "anthropic_api_key_env",
    "anthropic_base_url",
    "anthropic_version",
)


def _batch_overrides(args: argparse.Namespace) -> dict:
    """Map the run flags the user passed onto prediction fields for batch mode."""

    overrides: dict = {}
    if args.dry_run:
        overrides["dry_run"] = True
    if args.allow_synthetic_ops:
        overrides["allow_synthetic_ops"] = True
    if args.disable_coupling:
        overrides["disable_coupling"] = True
    if args.max_steps is not None:
        overrides["max_steps"] = args.max_steps
    if args.agent_config:
        # Like single-scenario runs, the profile defines both agents; it replaces
        # any agent settings (and profile) from the predictions file.
        profile = load_and_resolve_agent_profile(args.agent_config)
        overrides.update(
            agent_config="",
            agent_config_path=str(profile.get("agent_config_path", "")),
            agent_profile_name=str(profile.get("agent_profile_name", "")),
            code_agent_ref=str(profile.get("code_agent_ref", "")),
            aiops_agent_ref=str(profile.get("aiops_agent_ref", "")),
            code_agent_config=dict(profile.get("code_agent_config", {})),
            ops_agent_config=dict(profile.get("ops_agent_config", {})),
        )
    if args.code_agent_ref:
        overrides["code_agent_ref"] = args.code_agent_ref
    if args.aiops_agent_ref:
        overrides["aiops_agent_ref"] = args.aiops_agent_ref
    for field in _PROVIDER_FLAG_FIELDS:
        if getattr(args, field):
            overrides[field] = getattr(args, field)
    return overrides


def main() -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args()
    if args.doctor:
        return run_doctor()
    if args.run_local_demo:
        bundle = run_local_demo(args.run_local_demo)
        print(json.dumps(bundle, indent=2))
        return 0
    if args.write_markdown_report:
        if not args.evaluation_json:
            parser.error("--evaluation-json is required with --write-markdown-report")
        output_path = write_markdown_report_from_json(
            evaluation_json_path=args.evaluation_json,
            output_path=args.write_markdown_report,
        )
        print(str(output_path))
        return 0
    if args.write_run_markdown_report:
        if not args.run_dir:
            parser.error("--run-dir is required with --write-run-markdown-report")
        output_path = write_run_markdown_report(
            run_dir=args.run_dir,
            output_path=args.write_run_markdown_report,
        )
        print(str(output_path))
        return 0
    if args.write_readiness_report:
        bundle = build_readiness_bundle()
        output_path = Path(args.write_readiness_report)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
        print(json.dumps(bundle, indent=2))
        return 0
    if args.export_code_instance:
        if not args.scenario:
            parser.error("--scenario is required with --export-code-instance")
        instance = export_code_instance(
            scenario_path=args.scenario,
            output_path=args.export_code_instance,
        )
        print(json.dumps(instance, indent=2))
        return 0
    if args.manifest or args.predictions or args.evaluation_output:
        if not (args.manifest and args.predictions and args.evaluation_output):
            parser.error("--manifest, --predictions, and --evaluation-output must be provided together")
        for flag, value in (
            ("--scenario", args.scenario),
            ("--code-patch", args.code_patch),
            ("--validate-scenario", args.validate_scenario),
            ("--check-readiness", args.check_readiness),
        ):
            if value:
                parser.error(
                    f"{flag} cannot be used with --manifest batch evaluation; set "
                    "per-scenario inputs (e.g. code_patch_path) in the predictions file"
                )
        results = evaluate_predictions(
            manifest_path=args.manifest,
            predictions_path=args.predictions,
            output_path=args.evaluation_output,
            overrides=_batch_overrides(args),
            configure_run=lambda run_config: _apply_provider_overrides(run_config, args),
        )
        print(json.dumps(results, indent=2))
        return 0
    if not args.scenario:
        parser.error("--scenario is required unless --doctor is used")
    runner = ACBenchRunner()
    if args.validate_scenario:
        scenario = runner.load_scenario(args.scenario)
        print(json.dumps(scenario.to_dict(), indent=2))
        return 0
    if args.check_readiness:
        scenario = runner.load_scenario(args.scenario)
        report = check_scenario_readiness(scenario)
        print(json.dumps(report.to_dict(), indent=2))
        return 0
    agent_profile = (
        load_and_resolve_agent_profile(args.agent_config) if args.agent_config else {}
    )
    run_config = RunConfig(
        dry_run=args.dry_run,
        max_steps=args.max_steps if args.max_steps is not None else 10,
        allow_synthetic_ops=args.allow_synthetic_ops,
        disable_coupling=args.disable_coupling,
        code_agent_ref=args.code_agent_ref or str(agent_profile.get("code_agent_ref", "")),
        aiops_agent_ref=args.aiops_agent_ref or str(agent_profile.get("aiops_agent_ref", "")),
        agent_config_path=str(agent_profile.get("agent_config_path", "")),
        agent_profile_name=str(agent_profile.get("agent_profile_name", "")),
        code_agent_config=dict(agent_profile.get("code_agent_config", {})),
        ops_agent_config=dict(agent_profile.get("ops_agent_config", {})),
        code_patch_path=args.code_patch,
        openai_model=args.openai_model,
        openai_api_key_env=args.openai_api_key_env or "OPENAI_API_KEY",
        openai_base_url=args.openai_base_url,
        anthropic_model=args.anthropic_model,
        anthropic_api_key_env=args.anthropic_api_key_env or "ANTHROPIC_API_KEY",
        anthropic_base_url=args.anthropic_base_url or "https://api.anthropic.com",
        anthropic_version=args.anthropic_version or "2023-06-01",
        aiops_agent_type=args.aiops_agent_ref or "standalone-local-ops",
        code_agent_type=args.code_agent_ref or "unconfigured",
    )
    _apply_provider_overrides(run_config, args)
    result = runner.run(args.scenario, dry_run=args.dry_run, run_config=run_config)
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
