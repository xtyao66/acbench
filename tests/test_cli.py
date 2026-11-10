"""Tests for CLI utility output contracts."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from acbench.orchestrator.cli import build_parser, run_doctor


class CLITests(unittest.TestCase):
    def test_parser_accepts_aiops_agent_ref(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "--scenario",
                "tasks/scenarios/local/combined/billing_pricing__checkout_totals_incident.scenario.json",
                "--aiops-agent-ref",
                "acbench.agents.openai_ops:OpenAIOpsAgent",
            ]
        )

        self.assertEqual(
            args.aiops_agent_ref,
            "acbench.agents.openai_ops:OpenAIOpsAgent",
        )

    def test_run_doctor_reports_standalone_backend(self) -> None:
        stream = io.StringIO()
        with redirect_stdout(stream):
            result = run_doctor()

        payload = json.loads(stream.getvalue())
        self.assertEqual(result, 0)
        self.assertIn("acbench_code", payload)
        self.assertEqual(
            payload["acbench_code"]["extra_checks"]["backend_type"],
            "standalone-local-code",
        )

    def test_parser_accepts_anthropic_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "--scenario",
                "tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json",
                "--anthropic-model",
                "claude-sonnet-4-20250514",
                "--anthropic-api-key-env",
                "ANTHROPIC_API_KEY",
            ]
        )

        self.assertEqual(args.anthropic_model, "claude-sonnet-4-20250514")
        self.assertEqual(args.anthropic_api_key_env, "ANTHROPIC_API_KEY")

    def test_parser_accepts_agent_config(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "--scenario",
                "tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json",
                "--agent-config",
                "configs/agents/claude_sonnet.example.json",
            ]
        )

        self.assertEqual(args.agent_config, "configs/agents/claude_sonnet.example.json")


if __name__ == "__main__":
    unittest.main()
