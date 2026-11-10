"""Local synthetic ops executor for early combined-scenario validation."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from acbench.executors.base import BenchmarkExecutor
from acbench.executors.backends.ops.runner import (
    build_ops_request,
    run_ops_request,
    write_ops_artifacts,
)
from acbench.executors.backends.ops.runtime import NativeOpsProblem
from acbench.models.result import ExecutorResult
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec


class LocalOpsExecutor(BenchmarkExecutor):
    """Produce a minimal synthetic ops result without external dependencies."""

    def __init__(self) -> None:
        super().__init__(backend_name="acbench-local-ops")

    def execute(
        self,
        scenario: ScenarioSpec,
        run_dir: Path,
        run_config: RunConfig,
    ) -> ExecutorResult:
        started = perf_counter()
        problem = NativeOpsProblem.from_scenario(scenario)
        request = build_ops_request(
            problem,
            output_dir=run_dir / "ops_eval",
            max_steps=run_config.max_steps,
            agent_ref=run_config.aiops_agent_ref,
            keep_artifacts=run_config.keep_artifacts,
            allow_synthetic_ops=run_config.allow_synthetic_ops,
            ops_agent_config=run_config.ops_agent_config,
            openai_model=run_config.openai_model,
            openai_api_key_env=run_config.openai_api_key_env,
            openai_base_url=run_config.openai_base_url,
            anthropic_model=run_config.anthropic_model,
            anthropic_api_key_env=run_config.anthropic_api_key_env,
            anthropic_base_url=run_config.anthropic_base_url,
            anthropic_version=run_config.anthropic_version,
        )
        outcome = write_ops_artifacts(request, run_ops_request(request))
        outcome.metrics["executor_total_seconds"] = round(perf_counter() - started, 6)
        return outcome.to_executor_result(self.backend_name)
