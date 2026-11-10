"""Tests for the internal ops runner."""

from __future__ import annotations

import tempfile
import unittest
import json
from enum import Enum
from pathlib import Path

from acbench.executors.backends.ops.runner import (
    build_ops_request,
    run_ops_request,
    write_ops_artifacts,
)
from acbench.executors.backends.ops.runtime import NativeOpsProblem


class OpsRunnerTests(unittest.TestCase):
    def test_write_ops_artifacts_json_safes_enum_values(self) -> None:
        class SubmissionStatus(Enum):
            INCORRECT = "Incorrect"

        with tempfile.TemporaryDirectory() as tmp_dir:
            request = build_ops_request(
                NativeOpsProblem(
                    problem_id="p-1",
                    source="acbench",
                    application="app",
                    service="svc",
                ),
                output_dir=Path(tmp_dir),
                max_steps=1,
            )
            outcome = write_ops_artifacts(request, run_ops_request(request))
            outcome.metrics["status"] = SubmissionStatus.INCORRECT
            outcome = write_ops_artifacts(request, outcome)

            payload = json.loads(Path(outcome.logs["outcome_path"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["metrics"]["status"], "Incorrect")

    def test_build_ops_request_sets_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            problem = NativeOpsProblem(
                problem_id="p-1",
                source="acbench",
                application="app",
                service="svc",
            )

            request = build_ops_request(
                problem,
                output_dir=Path(tmp_dir),
                max_steps=7,
                agent_ref="agent:Class",
                keep_artifacts=False,
            )

            self.assertEqual(request.problem.problem_id, "p-1")
            self.assertEqual(request.output_dir, Path(tmp_dir))
            self.assertEqual(request.max_steps, 7)
            self.assertEqual(request.agent_ref, "agent:Class")
            self.assertFalse(request.keep_artifacts)

    def test_run_ops_request_uses_standalone_engine_for_acbench_problem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            outcome = run_ops_request(
                build_ops_request(
                    NativeOpsProblem(
                        problem_id="p-1",
                        source="acbench",
                        application="app",
                        service="svc",
                        require_detection=True,
                    ),
                    output_dir=Path(tmp_dir),
                    max_steps=4,
                    allow_synthetic_ops=True,
                )
            )

            self.assertTrue(outcome.success)
            self.assertTrue(outcome.detected)
            self.assertTrue(outcome.metrics["synthetic"])

    def test_write_ops_artifacts_persists_outcome_and_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            request = build_ops_request(
                NativeOpsProblem(
                    problem_id="p-1",
                    source="acbench",
                    application="app",
                    service="svc",
                ),
                output_dir=Path(tmp_dir),
                max_steps=4,
            )
            outcome = write_ops_artifacts(
                request,
                run_ops_request(request),
            )

            self.assertIn("outcome_path", outcome.logs)
            self.assertIn("trace_path", outcome.logs)
            outcome_payload = json.loads(
                Path(outcome.logs["outcome_path"]).read_text(encoding="utf-8")
            )
            trace_payload = json.loads(
                Path(outcome.logs["trace_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(outcome_payload["problem_id"], "p-1")
            self.assertEqual(trace_payload["agent_ref"], "")
            self.assertEqual(trace_payload["events"][0]["type"], "ops_run_started")


if __name__ == "__main__":
    unittest.main()
