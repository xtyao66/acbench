"""Tests for the local synthetic ops executor."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acbench.executors.local_ops import LocalOpsExecutor
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec


class LocalOpsExecutorTests(unittest.TestCase):
    def test_local_ops_executor_uses_internal_ops_runtime_contract(self) -> None:
        scenario = ScenarioSpec.from_dict(
            {
                "scenario_id": "local-ops-test",
                "title": "local ops",
                "mode": "ops_only",
                "service": {
                    "application": "app",
                    "service": "svc",
                },
                "ops_fault": {
                    "source": "acbench",
                    "problem_id": "p-1",
                    "description": "synthetic ops fault",
                    "detection_keywords": ["fault"],
                    "localization_keywords": ["svc"],
                },
                "success_criteria": {
                    "require_detection": True,
                    "require_localization": True,
                    "require_repair": False,
                },
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Default (no agent, no opt-in): not evaluated, no credit.
            not_evaluated = LocalOpsExecutor().execute(
                scenario=scenario,
                run_dir=Path(tmp_dir),
                run_config=RunConfig(dry_run=False, max_steps=5),
            )
            self.assertFalse(not_evaluated.success)
            self.assertFalse(not_evaluated.detected)
            self.assertEqual(not_evaluated.details["mode"], "ops-not-evaluated")

            # Opt-in synthetic placeholder restores the optimistic contract.
            result = LocalOpsExecutor().execute(
                scenario=scenario,
                run_dir=Path(tmp_dir) / "synthetic",
                run_config=RunConfig(dry_run=False, max_steps=5, allow_synthetic_ops=True),
            )

            self.assertIn("trace_path", result.logs)
            self.assertTrue(Path(result.logs["trace_path"]).exists())

        self.assertEqual(result.backend, "acbench-local-ops")
        self.assertTrue(result.success)
        self.assertTrue(result.detected)
        self.assertTrue(result.localized)
        self.assertFalse(result.repaired)
        self.assertTrue(result.metrics["synthetic"])
        self.assertEqual(result.details["mode"], "synthetic-local-ops")

    def test_local_ops_executor_can_use_agent_assessment(self) -> None:
        scenario = ScenarioSpec.from_dict(
            {
                "scenario_id": "agent-ops-test",
                "title": "agent ops",
                "mode": "ops_only",
                "service": {
                    "application": "queue-worker",
                    "service": "notification-consumer",
                },
                "task": {
                    "summary": "Triage queue incident",
                    "instructions": "Return a structured assessment.",
                },
                "visible_context": {
                    "error_logs": ["consumer lag rose sharply"],
                },
                "ops_fault": {
                    "source": "acbench",
                    "problem_id": "p-2",
                    "description": "agent driven ops fault",
                    "detection_keywords": ["lag"],
                    "localization_keywords": ["notification-consumer"],
                    "repair_keywords": ["repair"],
                },
                "success_criteria": {
                    "require_detection": True,
                    "require_localization": True,
                    "require_repair": True,
                },
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = LocalOpsExecutor().execute(
                scenario=scenario,
                run_dir=Path(tmp_dir),
                run_config=RunConfig(
                    dry_run=False,
                    max_steps=5,
                    aiops_agent_ref="tests.test_openai_ops_agent:FakeOpsAssessmentAgent",
                    openai_model="test-model",
                ),
            )

            self.assertTrue(Path(result.logs["trace_path"]).exists())
            self.assertTrue(Path(result.logs["outcome_path"]).exists())

        self.assertEqual(result.backend, "acbench-local-ops")
        self.assertTrue(result.success)
        self.assertFalse(result.metrics["synthetic"])
        self.assertEqual(result.details["mode"], "agent-driven-ops")
        self.assertEqual(result.metrics["agent_answer_count"], 1)
        self.assertIn("agent_telemetry", result.details)


if __name__ == "__main__":
    unittest.main()
