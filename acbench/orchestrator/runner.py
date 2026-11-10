"""Top-level runner for the standalone ACBench benchmark."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from time import perf_counter
import traceback

from acbench.executors.dry_run import DryRunCodeExecutor, DryRunOpsExecutor
from acbench.executors.local_code import LocalCodeExecutor
from acbench.executors.local_ops import LocalOpsExecutor
from acbench.models.result import BenchmarkResult, ExecutorResult
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec
from acbench.orchestrator.validate import check_scenario_readiness
from acbench.paths import repo_root, resolve_repo_path
from acbench.scoring import build_scorecard


class ACBenchRunner:
    """Coordinate ACBench scenario execution and result emission."""

    def __init__(self, root_dir: str | Path | None = None):
        self.root_dir = Path(root_dir) if root_dir else repo_root()
        # ACBENCH_RUNS_DIR moves run outputs out of the checkout (tests use it too).
        runs_override = os.environ.get("ACBENCH_RUNS_DIR", "") if root_dir is None else ""
        self.runs_dir = Path(runs_override) if runs_override else self.root_dir / "runs"

    def load_scenario(self, scenario_path: str | Path) -> ScenarioSpec:
        """Load and validate a scenario specification."""

        return ScenarioSpec.from_file(resolve_repo_path(scenario_path))

    def create_run_dir(self, scenario: ScenarioSpec) -> Path:
        """Create a stable per-run output directory."""

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        run_dir = self.runs_dir / f"{scenario.scenario_id}-{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    def select_ops_executor(self, dry_run: bool):
        """Select the ops executor implementation."""

        return DryRunOpsExecutor() if dry_run else LocalOpsExecutor()

    def select_ops_executor_for_scenario(self, scenario: ScenarioSpec, dry_run: bool):
        """Select the ops executor for one scenario."""

        if dry_run:
            return DryRunOpsExecutor()
        return LocalOpsExecutor()

    def select_code_executor(self, scenario: ScenarioSpec, dry_run: bool):
        """Select the code executor implementation."""

        if dry_run:
            return DryRunCodeExecutor()
        return LocalCodeExecutor()

    def run(
        self,
        scenario_path: str | Path,
        dry_run: bool = False,
        run_config: RunConfig | None = None,
        inline_patch: str | None = None,
    ) -> BenchmarkResult:
        """Run one benchmark scenario.

        ``inline_patch`` is patch text (e.g. a prediction's ``model_patch``); it
        is written into this run's own directory and used as the code patch.
        """

        run_config = run_config or RunConfig(dry_run=dry_run)
        started = perf_counter()
        scenario = self.load_scenario(scenario_path)
        self._validate_backend_bindings(scenario)
        readiness = check_scenario_readiness(scenario)
        if not run_config.dry_run and not readiness.ready_for_live_run:
            issue_summary = "; ".join(
                f"[{issue.source}] {issue.message}" for issue in readiness.issues
            )
            raise RuntimeError(
                "Scenario is not ready for live execution in the current environment: "
                f"{issue_summary}"
            )
        run_dir = self.create_run_dir(scenario)
        if inline_patch is not None:
            inline_patch_path = run_dir / "model_patch.diff"
            inline_patch_path.write_text(inline_patch, encoding="utf-8")
            run_config.code_patch_path = str(inline_patch_path)
        self._write_run_inputs(run_dir, scenario)
        result = BenchmarkResult(
            scenario_id=scenario.scenario_id,
            title=scenario.title,
            mode=scenario.mode,
        )
        diagnostics = self._collect_backend_diagnostics(scenario)
        diagnostics["run_config"] = {
            "dry_run": run_config.dry_run,
            "max_steps": run_config.max_steps,
            "keep_artifacts": run_config.keep_artifacts,
            "allow_synthetic_ops": run_config.allow_synthetic_ops,
            "aiops_agent_type": run_config.aiops_agent_type,
            "code_agent_type": run_config.code_agent_type,
            "aiops_agent_ref": run_config.aiops_agent_ref,
            "code_agent_ref": run_config.code_agent_ref,
            "agent_config_path": run_config.agent_config_path,
            "agent_profile_name": run_config.agent_profile_name,
            "code_patch_path": run_config.code_patch_path,
            "openai_model": run_config.openai_model,
            "openai_api_key_env": run_config.openai_api_key_env,
            "openai_base_url": run_config.openai_base_url,
            "anthropic_model": run_config.anthropic_model,
            "anthropic_api_key_env": run_config.anthropic_api_key_env,
            "anthropic_base_url": run_config.anthropic_base_url,
            "anthropic_version": run_config.anthropic_version,
            "disable_coupling": run_config.disable_coupling,
            # A patch file bypasses the code agent, so no code model is used.
            "code_agent_model": (
                ""
                if run_config.code_patch_path
                else self._effective_model(
                    run_config.code_agent_ref, run_config.code_agent_config, run_config
                )
            ),
            "ops_agent_model": self._effective_model(
                run_config.aiops_agent_ref, run_config.ops_agent_config, run_config
            ),
        }
        diagnostics["readiness"] = readiness.to_dict()
        diagnostics_path = self._write_json(run_dir / "diagnostics.json", diagnostics)

        if scenario.mode in {"ops_only", "combined"}:
            ops_executor = self.select_ops_executor_for_scenario(
                scenario=scenario,
                dry_run=run_config.dry_run,
            )
            result.ops_result = self._execute_with_capture(
                executor=ops_executor,
                scenario=scenario,
                run_dir=run_dir,
                run_config=run_config,
                result=result,
                stage_name="ops",
            )

        if (
            scenario.mode == "combined"
            and result.ops_result is not None
            and not run_config.disable_coupling
        ):
            # Couple the stages: feed the ops diagnosis into the code stage so the
            # repair is informed by the diagnosis instead of running independently.
            assessment = (
                result.ops_result.details.get("assessment")
                if isinstance(result.ops_result.details, dict)
                else None
            )
            if isinstance(assessment, dict) and assessment:
                run_config.upstream_ops_diagnosis = assessment

        if scenario.mode in {"code_only", "combined"}:
            code_executor = self.select_code_executor(
                scenario=scenario,
                dry_run=run_config.dry_run,
            )
            result.code_result = self._execute_with_capture(
                executor=code_executor,
                scenario=scenario,
                run_dir=run_dir,
                run_config=run_config,
                result=result,
                stage_name="code",
            )

        result.finalize(status=self._derive_status(result))
        result.unified_metrics = self._merge_metrics(result)
        result.unified_metrics.update(build_scorecard(scenario, result))
        result.unified_metrics["run_total_seconds"] = round(perf_counter() - started, 6)
        summary = self._build_summary(scenario, result)
        self._update_artifacts_from_results(result)

        result_path = run_dir / "result.json"
        summary_path = self._write_json(run_dir / "summary.json", summary)
        result.artifacts.result_path = str(result_path)
        result.artifacts.summary_path = str(summary_path)
        result.artifacts.scenario_path = str(run_dir / "scenario.json")
        result.artifacts.diagnostics_path = str(diagnostics_path)
        result.write_json(result_path)
        return result

    def _validate_backend_bindings(self, scenario: ScenarioSpec) -> None:
        """Validate scenario references against known backend metadata."""

        return None

    def _merge_metrics(self, result: BenchmarkResult) -> dict:
        """Merge executor metrics into one top-level summary."""

        unified = {}
        if result.ops_result:
            unified["ops_backend"] = result.ops_result.backend
            unified.update(
                {f"ops_{k}": v for k, v in result.ops_result.metrics.items()}
            )
            unified["ops_detected"] = result.ops_result.detected
            unified["ops_localized"] = result.ops_result.localized
            unified["ops_repaired"] = result.ops_result.repaired
        if result.code_result:
            unified["code_backend"] = result.code_result.backend
            unified.update(
                {f"code_{k}": v for k, v in result.code_result.metrics.items()}
            )
            unified["code_build_success"] = result.code_result.build_success
            unified["code_test_success"] = result.code_result.test_success
            unified["code_fail_to_pass_count"] = len(result.code_result.fail_to_pass_success)
            unified["code_pass_to_pass_count"] = len(result.code_result.pass_to_pass_success)
        unified["has_ops_result"] = result.ops_result is not None
        unified["has_code_result"] = result.code_result is not None
        return unified

    def _derive_status(self, result: BenchmarkResult) -> str:
        """Compute the top-level run status."""

        statuses = []
        if result.ops_result is not None:
            statuses.append(result.ops_result.success)
        if result.code_result is not None:
            statuses.append(result.code_result.success)
        return "success" if statuses and all(statuses) else "failed"

    def _write_run_inputs(self, run_dir: Path, scenario: ScenarioSpec) -> None:
        """Persist run input files for reproducibility."""

        self._write_json(run_dir / "scenario.json", scenario.to_dict())

    def _collect_backend_diagnostics(self, scenario: ScenarioSpec) -> dict:
        """Collect lightweight backend diagnostics for this run."""

        diagnostics = {
            "scenario_mode": scenario.mode,
            "ops_backend": None,
            "code_backend": None,
        }
        if scenario.mode in {"ops_only", "combined"} and scenario.ops_fault:
            diagnostics["ops_backend"] = {
                "source": scenario.ops_fault.source,
                "executor": "acbench-local-ops",
            }
        if scenario.mode in {"code_only", "combined"} and scenario.code_fault:
            diagnostics["code_backend"] = {
                "source": scenario.code_fault.source,
                "repository_path": scenario.service.repository_path or "",
                "executor": "acbench-local-code",
            }
        return diagnostics

    @staticmethod
    def _effective_model(agent_ref: str, section: dict, run_config: RunConfig) -> str:
        """Model an agent will call, resolved the way the built-in agents do."""

        if not agent_ref:
            return ""
        fallback = (
            run_config.anthropic_model if "anthropic" in agent_ref else run_config.openai_model
        )
        return str(section.get("model", fallback))

    @staticmethod
    def _write_json(path: Path, payload: dict) -> Path:
        """Write a JSON payload to disk."""

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        return path

    @staticmethod
    def _build_summary(scenario: ScenarioSpec, result: BenchmarkResult) -> dict:
        """Build a compact benchmark summary for fast inspection."""

        summary = {
            "scenario_id": result.scenario_id,
            "title": result.title,
            "mode": result.mode,
            "status": result.status,
            "source_type": scenario.source.type,
            "difficulty": scenario.metadata.difficulty or "unknown",
            "application": scenario.service.application,
            "service": scenario.service.service,
            "run_total_seconds": result.unified_metrics.get("run_total_seconds", 0.0),
            "final_score": result.unified_metrics.get("final_score", 0.0),
            "ops_score": result.unified_metrics.get("ops_score", 0.0),
            "code_score": result.unified_metrics.get("code_score", 0.0),
            "score_breakdown": result.unified_metrics.get("score_breakdown", {}),
            "failure_reasons": result.unified_metrics.get("failure_reasons", []),
            "ops": None,
            "code": None,
        }
        if result.ops_result:
            summary["ops"] = {
                "backend": result.ops_result.backend,
                "success": result.ops_result.success,
                "detected": result.ops_result.detected,
                "localized": result.ops_result.localized,
                "repaired": result.ops_result.repaired,
                "executor_total_seconds": result.ops_result.metrics.get(
                    "executor_total_seconds",
                    0.0,
                ),
                "agent_answer_count": result.ops_result.metrics.get(
                    "agent_answer_count",
                    0,
                ),
                "agent_total_answer_seconds": result.ops_result.metrics.get(
                    "agent_total_answer_seconds",
                    0.0,
                ),
                "agent_average_answer_seconds": result.ops_result.metrics.get(
                    "agent_average_answer_seconds",
                    0.0,
                ),
            }
        if result.code_result:
            summary["code"] = {
                "backend": result.code_result.backend,
                "success": result.code_result.success,
                "build_success": result.code_result.build_success,
                "test_success": result.code_result.test_success,
                "executor_total_seconds": result.code_result.metrics.get(
                    "executor_total_seconds",
                    0.0,
                ),
                "agent_answer_count": result.code_result.metrics.get(
                    "agent_answer_count",
                    0,
                ),
                "agent_total_answer_seconds": result.code_result.metrics.get(
                    "agent_total_answer_seconds",
                    0.0,
                ),
                "agent_average_answer_seconds": result.code_result.metrics.get(
                    "agent_average_answer_seconds",
                    0.0,
                ),
                "submitted_instance_id": result.code_result.metrics.get(
                    "submitted_instance_id",
                    "",
                ),
                "resolved": result.code_result.metrics.get("resolved", False),
                "pass_to_pass_count": len(result.code_result.pass_to_pass_success),
                "fail_to_pass_count": len(result.code_result.fail_to_pass_success),
                "pass_to_pass_failure_count": len(result.code_result.pass_to_pass_failure),
                "fail_to_pass_failure_count": len(result.code_result.fail_to_pass_failure),
            }
        return summary

    @staticmethod
    def _update_artifacts_from_results(result: BenchmarkResult) -> None:
        """Promote known executor log paths into top-level artifacts."""

        for executor_result in (result.ops_result, result.code_result):
            if not executor_result:
                continue
            logs = executor_result.logs
            if logs.get("trace_path"):
                result.artifacts.trace_path = logs["trace_path"]
            if logs.get("build_log_path"):
                result.artifacts.build_log_path = logs["build_log_path"]
            if logs.get("test_log_path"):
                result.artifacts.test_log_path = logs["test_log_path"]
            if logs.get("patch_path"):
                result.artifacts.patch_path = logs["patch_path"]
            if logs.get("outcome_path"):
                result.artifacts.telemetry_summary_path = logs["outcome_path"]

    @staticmethod
    def _execute_with_capture(
        executor,
        scenario: ScenarioSpec,
        run_dir: Path,
        run_config: RunConfig,
        result: BenchmarkResult,
        stage_name: str,
    ) -> ExecutorResult:
        """Capture executor failures as normalized benchmark results."""

        try:
            return executor.execute(scenario, run_dir, run_config)
        except Exception as exc:  # pragma: no cover - covered by tests via behavior
            exception_path = run_dir / f"{stage_name}_exception.txt"
            exception_path.write_text(traceback.format_exc(), encoding="utf-8")
            result.notes.append(
                f"{stage_name} executor failed: {type(exc).__name__}: {exc}"
            )
            telemetry_path, telemetry = ACBenchRunner._find_stage_telemetry(
                run_dir=run_dir,
                stage_name=stage_name,
            )
            metrics = {
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            }
            logs = {
                "exception_path": str(exception_path),
            }
            details = {
                "exception": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback_path": str(exception_path),
                }
            }
            if telemetry:
                metrics.update(
                    {
                        "agent_answer_count": int(telemetry.get("answer_count", 0)),
                        "agent_answer_durations_seconds": list(
                            telemetry.get("answer_durations_seconds", [])
                        ),
                        "agent_total_answer_seconds": float(
                            telemetry.get("total_answer_seconds", 0.0)
                        ),
                        "agent_average_answer_seconds": float(
                            telemetry.get("average_answer_seconds", 0.0)
                        ),
                        "agent_wall_time_seconds": float(
                            telemetry.get("wall_time_seconds", 0.0)
                        ),
                    }
                )
                details["agent_telemetry"] = telemetry
            if telemetry_path:
                logs["agent_telemetry_path"] = str(telemetry_path)
            return ExecutorResult(
                backend=getattr(executor, "backend_name", stage_name),
                success=False,
                metrics=metrics,
                logs=logs,
                details=details,
            )

    @staticmethod
    def _find_stage_telemetry(
        *,
        run_dir: Path,
        stage_name: str,
    ) -> tuple[Path | None, dict]:
        """Look for telemetry left behind by a partially failed stage."""

        search_dir = run_dir / "ops_eval" if stage_name == "ops" else run_dir
        candidates = sorted(search_dir.glob("*telemetry.json"))
        if not candidates:
            return None, {}
        telemetry_path = candidates[0]
        try:
            payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return telemetry_path, {}
        if not isinstance(payload, dict):
            return telemetry_path, {}
        return telemetry_path, payload
