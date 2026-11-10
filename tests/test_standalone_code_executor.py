"""Tests for API-backed standalone code execution hooks."""

from __future__ import annotations

import shutil
import tempfile
import unittest
import json
from pathlib import Path

from acbench.executors.standalone_code import StandaloneCodeExecutor
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec


class FakePatchAgent:
    """Return the known-good patch for the local buggy fixture."""

    def generate_patch(self, scenario, run_config, *, output_dir):
        patch_path = (
            Path(__file__).resolve().parents[1]
            / "patches"
            / "billing_pricing_bundle_fix.diff"
        )
        patch_text = patch_path.read_text(encoding="utf-8")
        generated_patch_path = output_dir / "fake_agent_patch.diff"
        telemetry_path = output_dir / "fake_code_telemetry.json"
        generated_patch_path.write_text(patch_text, encoding="utf-8")
        telemetry = {
            "answer_count": 1,
            "answer_durations_seconds": [0.2],
            "total_answer_seconds": 0.2,
            "average_answer_seconds": 0.2,
            "wall_time_seconds": 0.25,
            "answer_labels": ["initial_answer"],
        }
        telemetry_path.write_text(json.dumps(telemetry), encoding="utf-8")
        return {
            "patch_text": patch_text,
            "generated_patch_path": str(generated_patch_path),
            "telemetry": telemetry,
            "telemetry_path": str(telemetry_path),
        }


class StandaloneCodeExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="acbench-standalone-executor-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_executor_can_use_agent_generated_patch(self) -> None:
        scenario = ScenarioSpec.from_file(
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "scenarios"
            / "local"
            / "code"
            / "billing_pricing__bundle_discount_threshold.scenario.json"
        )
        executor = StandaloneCodeExecutor()

        result = executor.execute(
            scenario=scenario,
            run_dir=self.temp_dir / "run",
            run_config=RunConfig(
                code_agent_ref="tests.test_standalone_code_executor:FakePatchAgent",
                openai_model="test-model",
            ),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.backend, "acbench-code-standalone")
        self.assertIn("generated_patch_path", result.logs)
        self.assertTrue(Path(result.logs["generated_patch_path"]).exists())


if __name__ == "__main__":
    unittest.main()
