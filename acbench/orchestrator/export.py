"""Export helpers for standalone ACBench scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from acbench.executors.standalone_code import StandaloneCodeExecutor
from acbench.models.runtime import RunConfig
from acbench.orchestrator.runner import ACBenchRunner


def export_code_instance(
    scenario_path: str | Path,
    output_path: str | Path,
    use_gold_patch: bool = True,
) -> dict[str, Any]:
    """Export one ACBench scenario into a normalized code instance payload."""

    runner = ACBenchRunner()
    scenario_file = Path(scenario_path)
    scenario = runner.load_scenario(scenario_file)
    patch_path = scenario.gold_patch_path if use_gold_patch else ""

    run_result = runner.run(
        scenario_path=scenario_file,
        dry_run=False,
        run_config=RunConfig(
            dry_run=False,
            code_patch_path=patch_path,
            max_steps=10,
        ),
    )
    code_result = run_result.code_result
    if code_result is None:
        raise ValueError(f"Scenario {scenario.scenario_id} does not contain a code task.")

    run_config = RunConfig(dry_run=False, code_patch_path=patch_path, max_steps=10)
    instance = StandaloneCodeExecutor.build_instance_payload(scenario, run_config)
    instance["PASS_TO_PASS"] = list(code_result.pass_to_pass_success)
    instance["FAIL_TO_PASS"] = list(code_result.fail_to_pass_success)

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(instance, indent=2), encoding="utf-8")
    return instance
