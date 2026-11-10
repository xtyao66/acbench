"""Standalone repository-backed code executor owned by ACBench."""

from __future__ import annotations

import json
from pathlib import Path

from acbench.agents.loader import load_object
from acbench.executors.backends.code.runner import run_local_code_request
from acbench.executors.backends.code.runtime import CodeRunRequest, NativeCodeInstance
from acbench.executors.base import BenchmarkExecutor
from acbench.models.result import ExecutorResult
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec
from acbench.paths import resolve_repo_path


class StandaloneCodeExecutor(BenchmarkExecutor):
    """Execute repository-backed standalone code tasks."""

    def __init__(self) -> None:
        super().__init__(backend_name="acbench-code-standalone")

    def execute(
        self,
        scenario: ScenarioSpec,
        run_dir: Path,
        run_config: RunConfig,
    ) -> ExecutorResult:
        run_dir.mkdir(parents=True, exist_ok=True)
        agent_artifacts = self._resolve_agent_patch(scenario, run_config, run_dir)
        instance = self.build_instance_payload(
            scenario,
            run_config,
            patch_override=agent_artifacts.get("patch_text", ""),
        )
        instance_path = run_dir / "code_instance.json"
        instance_path.write_text(json.dumps(instance, indent=2), encoding="utf-8")
        prediction_path = run_dir / "code_prediction.json"
        prediction_path.write_text(
            json.dumps(self._build_prediction_payload(instance), indent=2),
            encoding="utf-8",
        )

        outcome = run_local_code_request(
            CodeRunRequest(
                instance=NativeCodeInstance.from_payload(instance),
                output_dir=run_dir / "code_eval",
                keep_workspace=run_config.keep_artifacts,
            )
        )
        result = self._normalize_outcome(outcome, instance)
        result.logs.update(
            {
                "instance_path": str(instance_path),
                "prediction_path": str(prediction_path),
                **{
                    key: value
                    for key, value in agent_artifacts.items()
                    if key != "patch_text"
                },
            }
        )
        return result

    @staticmethod
    def build_instance_payload(
        scenario: ScenarioSpec,
        run_config: RunConfig,
        patch_override: str = "",
    ) -> dict:
        patch_text = patch_override
        if not patch_text and run_config.code_patch_path:
            patch_file = resolve_repo_path(run_config.code_patch_path)
            if patch_file.exists():
                patch_text = patch_file.read_text(encoding="utf-8")
        repo_path = scenario.service.repository_path or ""
        resolved_repo_path = str(resolve_repo_path(repo_path)) if repo_path else ""
        return {
            "instance_id": scenario.scenario_id,
            "repo": resolved_repo_path,
            "platform": scenario.code_fault.platform if scenario.code_fault else "windows",
            "rebuild_cmds": list(scenario.build.rebuild_cmds),
            "test_cmds": list(scenario.build.test_cmds),
            "print_cmds": list(scenario.build.print_cmds),
            "log_parser": scenario.build.log_parser or "none",
            "test_patch": "",
            "patch": patch_text,
            "pred_patch": patch_text,
            "PASS_TO_PASS": [],
            "FAIL_TO_PASS": [],
        }

    @staticmethod
    def _build_prediction_payload(instance: dict) -> dict:
        return {
            instance["instance_id"]: {
                "model_patch": instance.get("pred_patch", ""),
            }
        }

    def _normalize_outcome(self, outcome, instance: dict) -> ExecutorResult:
        return ExecutorResult(
            backend=self.backend_name,
            success=outcome.resolved,
            repaired=outcome.resolved,
            build_success=outcome.resolved,
            test_success=outcome.resolved,
            pass_to_pass_success=list(outcome.pass_to_pass_success),
            pass_to_pass_failure=list(outcome.pass_to_pass_failure),
            fail_to_pass_success=list(outcome.fail_to_pass_success),
            fail_to_pass_failure=list(outcome.fail_to_pass_failure),
            metrics={
                "submitted_instance_id": instance.get("instance_id", ""),
                "resolved": outcome.resolved,
            },
            logs=dict(outcome.logs),
            details=dict(outcome.details),
        )

    def _resolve_agent_patch(
        self,
        scenario: ScenarioSpec,
        run_config: RunConfig,
        run_dir: Path,
    ) -> dict[str, str]:
        if run_config.code_patch_path or not run_config.code_agent_ref:
            return {}

        agent_cls = load_object(run_config.code_agent_ref)
        agent = agent_cls()
        if not hasattr(agent, "generate_patch"):
            raise ValueError(
                f"Configured code agent `{run_config.code_agent_ref}` does not expose `generate_patch`."
            )
        return agent.generate_patch(
            scenario=scenario,
            run_config=run_config,
            output_dir=run_dir,
        )
