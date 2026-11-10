"""Tests for the Anthropic-backed ops assessment agent."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acbench.agents.anthropic_ops import AnthropicOpsAgent
from acbench.executors.backends.ops.runtime import NativeOpsProblem
from acbench.models.runtime import RunConfig


class AnthropicOpsAgentTests(unittest.TestCase):
    def test_agent_configures_from_run_config(self) -> None:
        agent = AnthropicOpsAgent()
        agent.configure(
            RunConfig(
                anthropic_model="claude-test",
                anthropic_api_key_env="TEST_ANTHROPIC_KEY",
                anthropic_base_url="https://example.invalid",
                anthropic_version="2099-01-01",
            )
        )
        self.assertEqual(agent.model, "claude-test")
        self.assertEqual(agent.api_key_env, "TEST_ANTHROPIC_KEY")
        self.assertEqual(agent.base_url, "https://example.invalid")
        self.assertEqual(agent.version, "2099-01-01")

    def test_agent_analyze_writes_prompt_response_and_assessment(self) -> None:
        agent = AnthropicOpsAgent()
        agent.configure(RunConfig(anthropic_model="claude-test"))
        problem = NativeOpsProblem(
            problem_id="ops-claude-1",
            source="acbench",
            application="queue-worker",
            service="notification-consumer",
            task_summary="Triage a backlog incident.",
            task_instructions="Use the evidence and return a structured answer.",
            issue_text="Queue backlog spiked.",
            require_detection=True,
            require_localization=True,
            require_repair=True,
        )
        response = json.dumps(
            {
                "detected": True,
                "localized": True,
                "repaired": True,
                "summary": "The backlog incident is real.",
                "root_cause": "The worker tier is stuck.",
                "remediation": "Restart the worker and increase concurrency.",
                "evidence": ["consumer lag rose from 12s to 540s"],
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                with patch(
                    "acbench.agents.anthropic_ops.anthropic_messages_create",
                    return_value=response,
                ):
                    artifacts = agent.analyze(problem, output_dir=Path(tmp_dir))
            self.assertTrue(Path(artifacts["prompt_path"]).exists())
            self.assertTrue(Path(artifacts["response_path"]).exists())
            self.assertTrue(Path(artifacts["assessment_path"]).exists())
            self.assertTrue(artifacts["assessment"]["repaired"])
            self.assertEqual(artifacts["telemetry"]["answer_count"], 1)
            self.assertEqual(len(artifacts["telemetry"]["answer_durations_seconds"]), 1)
            self.assertTrue(Path(artifacts["telemetry_path"]).exists())
            self.assertIn("structured answer", agent.last_prompt)
            self.assertIn("Restart the worker", agent.last_response)
            self.assertTrue(agent.last_assessment["detected"])


if __name__ == "__main__":
    unittest.main()
