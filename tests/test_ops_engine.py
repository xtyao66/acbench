"""Tests for internal ops engine helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acbench.executors.backends.ops.engine import (
    AgentDrivenOpsEngine,
    StandaloneLocalOpsEngine,
    build_default_engine,
    build_engine_for_request,
    build_engine_for_problem,
)
from acbench.executors.backends.ops.runtime import NativeOpsProblem, OpsRunRequest


class OpsEngineTests(unittest.TestCase):
    def _problem(self) -> NativeOpsProblem:
        return NativeOpsProblem(
            problem_id="p-1",
            source="acbench",
            application="app",
            service="svc",
            require_detection=True,
            require_localization=True,
            require_repair=False,
        )

    def test_standalone_engine_does_not_auto_pass_without_opt_in(self) -> None:
        engine = StandaloneLocalOpsEngine()
        with tempfile.TemporaryDirectory() as tmp_dir:
            outcome = engine.run(
                OpsRunRequest(
                    problem=self._problem(),
                    output_dir=Path(tmp_dir),
                    max_steps=5,
                )
            )

        # Default: no agent and no opt-in -> not evaluated, no credit.
        self.assertFalse(outcome.success)
        self.assertFalse(outcome.detected)
        self.assertFalse(outcome.localized)
        self.assertEqual(outcome.details["mode"], "ops-not-evaluated")
        self.assertFalse(outcome.metrics["evaluated"])

    def test_standalone_engine_synthetic_outcome_requires_opt_in(self) -> None:
        engine = StandaloneLocalOpsEngine()
        with tempfile.TemporaryDirectory() as tmp_dir:
            outcome = engine.run(
                OpsRunRequest(
                    problem=self._problem(),
                    output_dir=Path(tmp_dir),
                    max_steps=5,
                    allow_synthetic_ops=True,
                )
            )

        self.assertTrue(outcome.success)
        self.assertTrue(outcome.detected)
        self.assertTrue(outcome.localized)
        self.assertFalse(outcome.repaired)
        self.assertEqual(outcome.metrics["TTD"], 1.0)
        self.assertEqual(outcome.details["mode"], "synthetic-local-ops")

    def test_build_engine_for_problem_uses_standalone_for_acbench_source(self) -> None:
        engine = build_engine_for_problem(
            NativeOpsProblem(
                problem_id="p-1",
                source="acbench",
                application="app",
                service="svc",
            )
        )

        self.assertIsInstance(engine, StandaloneLocalOpsEngine)

    def test_build_default_engine_uses_standalone_local_engine(self) -> None:
        engine = build_default_engine()
        self.assertIsInstance(engine, StandaloneLocalOpsEngine)

    def test_build_engine_for_request_uses_agent_when_ref_is_present(self) -> None:
        request = OpsRunRequest(
            problem=NativeOpsProblem(
                problem_id="p-1",
                source="acbench",
                application="app",
                service="svc",
            ),
            output_dir=Path("/tmp"),
            agent_ref="tests.test_openai_ops_agent:FakeOpsAssessmentAgent",
        )

        engine = build_engine_for_request(request)

        self.assertIsInstance(engine, AgentDrivenOpsEngine)

    def test_agent_driven_engine_scores_structured_assessment(self) -> None:
        engine = AgentDrivenOpsEngine()
        with tempfile.TemporaryDirectory() as tmp_dir:
            outcome = engine.run(
                OpsRunRequest(
                    problem=NativeOpsProblem(
                        problem_id="p-1",
                        source="acbench",
                        application="queue-worker",
                        service="notification-consumer",
                        error_logs=["consumer lag rose sharply"],
                        require_detection=True,
                        require_localization=True,
                        require_repair=True,
                        # Not visible in the prompt (log text, service name), so
                        # every stage is gradeable.
                        detection_keywords=["backlog"],
                        localization_keywords=["ack timeout"],
                        repair_keywords=["repair"],
                    ),
                    output_dir=Path(tmp_dir),
                    max_steps=5,
                    agent_ref="tests.test_openai_ops_agent:FakeOpsAssessmentAgent",
                )
            )

        self.assertTrue(outcome.success)
        self.assertTrue(outcome.detected)
        self.assertTrue(outcome.localized)
        self.assertTrue(outcome.repaired)
        self.assertFalse(outcome.metrics["synthetic"])
        self.assertEqual(outcome.details["mode"], "agent-driven-ops")


if __name__ == "__main__":
    unittest.main()
