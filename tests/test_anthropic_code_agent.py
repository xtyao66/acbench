"""Tests for the Anthropic-backed code patch agent."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acbench.agents.anthropic_code import AnthropicCodePatchAgent
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec


class AnthropicCodePatchAgentTests(unittest.TestCase):
    def test_generate_patch_writes_prompt_response_and_patch(self) -> None:
        scenario = ScenarioSpec.from_file(
            "tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json"
        )
        run_config = RunConfig(
            anthropic_model="claude-test",
            anthropic_api_key_env="TEST_ANTHROPIC_KEY",
        )
        patch_text = Path("patches/billing_pricing_bundle_fix.diff").read_text(
            encoding="utf-8"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"TEST_ANTHROPIC_KEY": "test-key"}):
                with patch(
                    "acbench.agents.anthropic_code.anthropic_messages_create",
                    return_value=patch_text,
                ):
                    artifacts = AnthropicCodePatchAgent().generate_patch(
                        scenario,
                        run_config,
                        output_dir=Path(tmp_dir),
                    )

            self.assertTrue(Path(artifacts["prompt_path"]).exists())
            self.assertTrue(Path(artifacts["response_path"]).exists())
            self.assertTrue(Path(artifacts["generated_patch_path"]).exists())
            self.assertIn("--- a/", artifacts["patch_text"])
            self.assertEqual(artifacts["telemetry"]["answer_count"], 1)
            self.assertEqual(len(artifacts["telemetry"]["answer_durations_seconds"]), 1)
            self.assertTrue(Path(artifacts["telemetry_path"]).exists())


if __name__ == "__main__":
    unittest.main()
