"""Tests for internal ops runtime models."""

from __future__ import annotations

import tempfile
import unittest
from enum import Enum
from pathlib import Path

from acbench.executors.backends.ops.runtime import (
    NativeOpsProblem,
    OpsRunOutcome,
    OpsRunRequest,
)
from acbench.models.scenario import ScenarioSpec


class OpsRuntimeTests(unittest.TestCase):
    def test_ops_run_outcome_to_executor_payload_json_safes_enums(self) -> None:
        class SubmissionStatus(Enum):
            CORRECT = "Correct"

        outcome = OpsRunOutcome(
            detected=True,
            success=True,
            metrics={"status": SubmissionStatus.CORRECT},
            details={"nested": {"status": SubmissionStatus.CORRECT}},
        )

        payload = outcome.to_executor_payload("acbench-local-ops")

        self.assertEqual(payload["metrics"]["status"], "Correct")
        self.assertEqual(payload["details"]["nested"]["status"], "Correct")

    def test_native_ops_problem_from_scenario(self) -> None:
        scenario = ScenarioSpec.from_dict(
            {
                "scenario_id": "ops-runtime-test",
                "title": "ops runtime",
                "mode": "ops_only",
                "service": {
                    "application": "astronomy-shop",
                    "service": "product-catalog",
                },
                "task": {
                    "summary": "Detect synthetic ops issue",
                    "instructions": "Use the evidence to localize the problem.",
                },
                "visible_context": {
                    "issue_text": "Catalog updates are stale.",
                    "error_logs": ["freshness lag exceeded SLO"],
                },
                "ops_fault": {
                    "source": "acbench",
                    "problem_id": "p-1",
                    "description": "synthetic fault",
                    "detection_keywords": ["stale"],
                    "localization_keywords": ["catalog"],
                },
                "success_criteria": {
                    "require_detection": True,
                    "require_localization": True,
                    "require_repair": False,
                },
            }
        )

        problem = NativeOpsProblem.from_scenario(scenario)

        self.assertEqual(problem.problem_id, "p-1")
        self.assertEqual(problem.source, "acbench")
        self.assertEqual(problem.application, "astronomy-shop")
        self.assertTrue(problem.require_detection)
        self.assertTrue(problem.require_localization)
        self.assertFalse(problem.require_repair)
        self.assertEqual(problem.task_summary, "Detect synthetic ops issue")
        self.assertEqual(problem.issue_text, "Catalog updates are stale.")
        self.assertIn("stale", problem.detection_keywords)

    def test_ops_run_outcome_to_executor_payload(self) -> None:
        outcome = OpsRunOutcome(
            detected=True,
            localized=True,
            repaired=False,
            success=True,
            metrics={"TTD": 1.0},
            logs={"trace_path": "trace.json"},
            details={"mode": "synthetic"},
        )

        payload = outcome.to_executor_payload("acbench-ops")

        self.assertEqual(payload["backend"], "acbench-ops")
        self.assertTrue(payload["success"])
        self.assertTrue(payload["detected"])
        self.assertEqual(payload["metrics"]["TTD"], 1.0)
        self.assertEqual(payload["logs"]["trace_path"], "trace.json")

    def test_ops_run_outcome_to_executor_result(self) -> None:
        outcome = OpsRunOutcome(
            detected=True,
            localized=False,
            repaired=False,
            success=True,
            metrics={"TTD": 1.0},
            details={"mode": "synthetic"},
        )

        result = outcome.to_executor_result("acbench-local-ops")

        self.assertEqual(result.backend, "acbench-local-ops")
        self.assertTrue(result.success)
        self.assertTrue(result.detected)
        self.assertFalse(result.localized)
        self.assertEqual(result.metrics["TTD"], 1.0)

    def test_ops_run_request_keeps_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            request = OpsRunRequest(
                problem=NativeOpsProblem(
                    problem_id="p-1",
                    source="acbench",
                    application="app",
                    service="svc",
                ),
                output_dir=Path(tmp_dir),
                max_steps=3,
                agent_ref="agent:Class",
            )

            self.assertEqual(request.output_dir, Path(tmp_dir))
            self.assertEqual(request.max_steps, 3)
            self.assertEqual(request.agent_ref, "agent:Class")


if __name__ == "__main__":
    unittest.main()
