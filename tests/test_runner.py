"""Basic tests for the ACBench skeleton."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import json

from acbench.agents.profile import load_and_resolve_agent_profile
from acbench.executors.base import BenchmarkExecutor
from acbench.executors.local_code import LocalCodeExecutor
from acbench.executors.standalone_code import StandaloneCodeExecutor
from acbench.models.result import ExecutorResult
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec
from acbench.orchestrator.runner import ACBenchRunner
from acbench.orchestrator.validate import check_scenario_readiness


class ScenarioModelTests(unittest.TestCase):
    def test_combined_requires_both_faults(self) -> None:
        with self.assertRaises(ValueError):
            ScenarioSpec.from_dict(
                {
                    "scenario_id": "bad-combined",
                    "title": "bad",
                    "mode": "combined",
                    "service": {
                        "application": "app",
                        "service": "svc",
                    },
                    "build": {
                        "test_cmds": ["pytest"],
                    },
                }
            )

    def test_github_scenarios_require_repo_url_and_commit(self) -> None:
        with self.assertRaises(ValueError):
            ScenarioSpec.from_dict(
                {
                    "scenario_id": "github-missing-commit",
                    "title": "bad github scenario",
                    "mode": "code_only",
                    "source": {
                        "type": "github",
                        "repo_url": "https://github.com/example/project",
                    },
                    "service": {
                        "application": "example",
                        "service": "svc",
                        "deployment": "local",
                    },
                    "code_fault": {
                        "source": "acbench",
                        "defect_id": "example-001",
                    },
                    "build": {
                        "test_cmds": ["pytest"],
                    },
                }
            )

    def test_extended_scenario_fields_are_loaded(self) -> None:
        scenario = ScenarioSpec.from_dict(
            {
                "scenario_id": "extended-local",
                "title": "extended local scenario",
                "mode": "code_only",
                "source": {
                    "type": "local_fixture",
                    "snapshot_key": "fixture-a",
                },
                "service": {
                    "application": "example",
                    "service": "svc",
                    "deployment": "local",
                    "repository_path": "/tmp/example",
                },
                "task": {
                    "summary": "repair a seeded defect",
                    "instructions": "fix the bug and preserve passing tests",
                },
                "visible_context": {
                    "reproduction_steps": ["run tests"],
                    "relevant_files": ["src/example.py"],
                },
                "code_fault": {
                    "source": "acbench",
                    "defect_id": "example-001",
                },
                "environment": {
                    "setup_cmds": ["python -m pip install -e ."],
                    "env_vars": {"PYTHONPATH": "src"},
                },
                "build": {
                    "test_cmds": ["pytest"],
                },
                "success_criteria": {
                    "require_test_success": True,
                },
                "evaluation": {
                    "strategy": "behavioral",
                    "required_tests": ["tests/test_example.py::test_bug"],
                },
                "constraints": {
                    "allow_network": False,
                    "allow_test_changes": False,
                    "max_runtime_minutes": 15,
                },
                "metadata": {
                    "difficulty": "medium",
                    "language": "python",
                    "categories": ["code-repair"],
                },
            }
        )

        self.assertEqual(scenario.source.snapshot_key, "fixture-a")
        self.assertEqual(scenario.task.summary, "repair a seeded defect")
        self.assertEqual(scenario.visible_context.relevant_files, ["src/example.py"])
        self.assertEqual(scenario.environment.env_vars["PYTHONPATH"], "src")
        self.assertEqual(
            scenario.evaluation.required_tests,
            ["tests/test_example.py::test_bug"],
        )
        self.assertEqual(scenario.metadata.difficulty, "medium")


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="acbench-test-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_dry_run_combined_scenario_writes_result(self) -> None:
        runner = ACBenchRunner(root_dir=self.temp_dir)
        scenario_path = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "scenarios"
            / "local"
            / "combined"
            / "billing_pricing__checkout_totals_incident.scenario.json"
        )

        result = runner.run(scenario_path, dry_run=True)

        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.ops_result)
        self.assertTrue(Path(result.artifacts.result_path).exists())
        self.assertTrue(Path(result.artifacts.summary_path).exists())
        self.assertTrue(Path(result.artifacts.scenario_path).exists())
        self.assertTrue(Path(result.artifacts.diagnostics_path).exists())
        self.assertIn("run_total_seconds", result.unified_metrics)
    def test_live_run_is_blocked_when_environment_is_not_ready(self) -> None:
        runner = ACBenchRunner(root_dir=self.temp_dir)
        scenario_path = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "scenarios"
            / "local"
            / "combined"
            / "billing_pricing__checkout_totals_incident.scenario.json"
        )

        class FakeIssue:
            source = "test"
            message = "synthetic readiness failure"

        class FakeReadiness:
            ready_for_live_run = False
            issues = [FakeIssue()]

            @staticmethod
            def to_dict() -> dict:
                return {
                    "ready_for_live_run": False,
                    "issues": [{"source": "test", "message": "synthetic readiness failure"}],
                }

        with patch(
            "acbench.orchestrator.runner.check_scenario_readiness",
            return_value=FakeReadiness(),
        ):
            with self.assertRaises(RuntimeError):
                runner.run(scenario_path, dry_run=False)

    def test_executor_failure_is_captured_into_result_artifacts(self) -> None:
        runner = ACBenchRunner(root_dir=self.temp_dir)
        scenario_path = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "scenarios"
            / "local"
            / "code"
            / "billing_pricing__bundle_discount_threshold.scenario.json"
        )

        class FailingExecutor(BenchmarkExecutor):
            def __init__(self) -> None:
                super().__init__(backend_name="failing-code")

            def execute(self, scenario, run_dir, run_config) -> ExecutorResult:
                raise RuntimeError("synthetic executor failure")

        with patch.object(
            ACBenchRunner,
            "select_code_executor",
            return_value=FailingExecutor(),
        ):
            result = runner.run(
                scenario_path,
                dry_run=False,
                run_config=RunConfig(dry_run=False),
            )

        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.code_result)
        self.assertEqual(result.code_result.backend, "failing-code")
        self.assertFalse(result.code_result.success)
        self.assertIn("synthetic executor failure", result.notes[0])
        self.assertTrue(Path(result.artifacts.result_path).exists())
        self.assertTrue(Path(result.artifacts.summary_path).exists())
        exception_path = Path(result.code_result.logs["exception_path"])
        self.assertTrue(exception_path.exists())
        self.assertIn("synthetic executor failure", exception_path.read_text(encoding="utf-8"))

    def test_code_summary_contains_code_specific_fields(self) -> None:
        runner = ACBenchRunner(root_dir=self.temp_dir)
        scenario_path = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "scenarios"
            / "local"
            / "code"
            / "billing_pricing__bundle_discount_threshold.scenario.json"
        )

        result = runner.run(
            scenario_path,
            dry_run=False,
            run_config=RunConfig(
                dry_run=False,
                code_patch_path=str(
                    Path(__file__).resolve().parents[1]
                    / "patches"
                    / "billing_pricing_bundle_fix.diff"
                ),
            ),
        )

        summary = Path(result.artifacts.summary_path).read_text(encoding="utf-8")
        self.assertIn("\"submitted_instance_id\"", summary)
        self.assertIn("\"resolved\"", summary)

    def test_local_combined_promotes_ops_trace_artifacts(self) -> None:
        runner = ACBenchRunner(root_dir=self.temp_dir)
        scenario_path = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "scenarios"
            / "local"
            / "combined"
            / "billing_pricing__checkout_totals_incident.scenario.json"
        )
        patch_path = (
            Path(__file__).resolve().parents[1]
            / "patches"
            / "billing_pricing_bundle_fix.diff"
        )

        result = runner.run(
            scenario_path,
            dry_run=False,
            run_config=RunConfig(
                dry_run=False,
                code_patch_path=str(patch_path),
                max_steps=5,
            ),
        )

        self.assertTrue(Path(result.artifacts.trace_path).exists())
        self.assertTrue(Path(result.artifacts.telemetry_summary_path).exists())

    def test_acbench_local_code_executor_can_use_agent_generated_patch(self) -> None:
        runner = ACBenchRunner(root_dir=self.temp_dir)
        scenario_path = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "scenarios"
            / "local"
            / "code"
            / "billing_pricing__bundle_discount_threshold.scenario.json"
        )

        executor = runner.select_code_executor(
            ScenarioSpec.from_file(scenario_path),
            dry_run=False,
        )
        self.assertIsInstance(executor, LocalCodeExecutor)

        result = runner.run(
            scenario_path,
            dry_run=False,
            run_config=RunConfig(
                dry_run=False,
                code_agent_ref="tests.test_standalone_code_executor:FakePatchAgent",
                openai_model="test-model",
            ),
        )

        self.assertEqual(result.code_result.backend, "acbench-local-code")
        self.assertTrue(result.code_result.success)
        self.assertTrue(Path(result.code_result.details["code_patch_path"]).exists())
        self.assertEqual(result.code_result.metrics["agent_answer_count"], 1)
        self.assertIn("agent_telemetry", result.code_result.details)

    def test_runner_can_use_generic_agent_profile(self) -> None:
        runner = ACBenchRunner(root_dir=self.temp_dir)
        scenario_path = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "scenarios"
            / "local"
            / "code"
            / "billing_pricing__bundle_discount_threshold.scenario.json"
        )
        profile_path = self.temp_dir / "fake_agent_profile.json"
        profile_path.write_text(
            json.dumps(
                {
                    "name": "fake-code-agent",
                    "code": {
                        "provider": "custom",
                        "agent_ref": "tests.test_standalone_code_executor:FakePatchAgent",
                    },
                }
            ),
            encoding="utf-8",
        )
        resolved = load_and_resolve_agent_profile(profile_path)

        result = runner.run(
            scenario_path,
            dry_run=False,
            run_config=RunConfig(
                dry_run=False,
                code_agent_ref=resolved["code_agent_ref"],
                agent_config_path=resolved["agent_config_path"],
                agent_profile_name=resolved["agent_profile_name"],
                code_agent_config=resolved["code_agent_config"],
            ),
        )

        self.assertTrue(result.code_result.success)
        self.assertEqual(result.code_result.metrics["agent_answer_count"], 1)

    def test_third_party_ops_source_is_ready_and_runs_live(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (
                repo_root / "tasks" / "scenarios" / "local" / "ops"
                / "queue_worker__backlog_spike.scenario.json"
            ).read_text(encoding="utf-8")
        )
        payload["ops_fault"]["source"] = "acme-taskpack"
        scenario_path = self.temp_dir / "third_party.scenario.json"
        scenario_path.write_text(json.dumps(payload), encoding="utf-8")

        readiness = check_scenario_readiness(ScenarioSpec.from_file(scenario_path))
        self.assertTrue(readiness.ready_for_live_run, readiness.to_dict())

        result = ACBenchRunner(root_dir=self.temp_dir).run(
            scenario_path,
            run_config=RunConfig(aiops_agent_ref="acbench.agents.gold_ops:GoldOpsAgent"),
        )
        self.assertEqual(result.ops_result.backend, "acbench-local-ops")

    def test_inline_patch_is_written_into_the_run_directory(self) -> None:
        scenario_path = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "scenarios"
            / "local"
            / "code"
            / "billing_pricing__bundle_discount_threshold.scenario.json"
        )

        result = ACBenchRunner(root_dir=self.temp_dir).run(
            scenario_path, dry_run=True, inline_patch="diff --git a/x b/x\n"
        )

        run_dir = Path(result.artifacts.result_path).parent
        patch_file = run_dir / "model_patch.diff"
        self.assertEqual(patch_file.read_text(encoding="utf-8"), "diff --git a/x b/x\n")
        diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
        self.assertEqual(diagnostics["run_config"]["code_patch_path"], str(patch_file))

    def test_diagnostics_record_coupling_and_effective_models(self) -> None:
        scenario_path = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "scenarios"
            / "local"
            / "combined"
            / "billing_pricing__checkout_totals_incident.scenario.json"
        )

        result = ACBenchRunner(root_dir=self.temp_dir).run(
            scenario_path,
            dry_run=True,
            run_config=RunConfig(
                dry_run=True,
                disable_coupling=True,
                code_agent_ref="acbench.agents.anthropic_code:AnthropicCodePatchAgent",
                anthropic_model="claude-test",
                aiops_agent_ref="acbench.agents.openai_ops:OpenAIOpsAgent",
                openai_model="top-level-model",
                ops_agent_config={"provider": "openai", "model": "profile-model"},
            ),
        )

        diagnostics = json.loads(
            Path(result.artifacts.diagnostics_path).read_text(encoding="utf-8")
        )["run_config"]
        self.assertTrue(diagnostics["disable_coupling"])
        self.assertEqual(diagnostics["code_agent_model"], "claude-test")
        self.assertEqual(diagnostics["ops_agent_model"], "profile-model")


if __name__ == "__main__":
    unittest.main()
