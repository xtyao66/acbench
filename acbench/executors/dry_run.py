"""Safe dry-run executors used to validate the ACBench skeleton."""

from __future__ import annotations

from pathlib import Path

from acbench.executors.base import BenchmarkExecutor
from acbench.models.result import ExecutorResult
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec


class DryRunOpsExecutor(BenchmarkExecutor):
    """Non-destructive ops executor for early validation."""

    def __init__(self) -> None:
        super().__init__(backend_name="dry-run-ops")

    def execute(
        self,
        scenario: ScenarioSpec,
        run_dir: Path,
        run_config: RunConfig,
    ) -> ExecutorResult:
        details = {
            "message": "Dry-run ops executor completed without touching a live cluster.",
            "problem_id": scenario.ops_fault.problem_id if scenario.ops_fault else "",
            "application": scenario.service.application,
            "service": scenario.service.service,
            "max_steps": run_config.max_steps,
        }
        return ExecutorResult(
            backend=self.backend_name,
            success=True,
            detected=scenario.success_criteria.require_detection,
            localized=scenario.success_criteria.require_localization,
            repaired=scenario.success_criteria.require_repair,
            deploy_success=False,
            metrics={"dry_run": True, "executor": "ops"},
            details=details,
        )


class DryRunCodeExecutor(BenchmarkExecutor):
    """Non-destructive code executor for early validation."""

    def __init__(self) -> None:
        super().__init__(backend_name="dry-run-code")

    def execute(
        self,
        scenario: ScenarioSpec,
        run_dir: Path,
        run_config: RunConfig,
    ) -> ExecutorResult:
        details = {
            "message": "Dry-run code executor completed without modifying repository files.",
            "defect_id": scenario.code_fault.defect_id if scenario.code_fault else "",
            "repository_path": scenario.service.repository_path or "",
            "test_cmd_count": len(scenario.build.test_cmds),
            "max_steps": run_config.max_steps,
        }
        return ExecutorResult(
            backend=self.backend_name,
            success=True,
            build_success=scenario.success_criteria.require_build_success,
            test_success=scenario.success_criteria.require_test_success,
            repaired=scenario.success_criteria.require_repair,
            metrics={"dry_run": True, "executor": "code"},
            details=details,
        )
