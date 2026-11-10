"""Tests for generic agent profile loading."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from acbench.agents.profile import (
    apply_agent_profile_to_payload,
    load_and_resolve_agent_profile,
)


class AgentProfileTests(unittest.TestCase):
    def test_load_and_resolve_provider_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile_path = Path(tmp_dir) / "claude.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "name": "claude-sonnet",
                        "code": {
                            "provider": "anthropic",
                            "model": "claude-test",
                            "api_key_env": "ANTHROPIC_API_KEY",
                        },
                        "ops": {
                            "provider": "anthropic",
                            "model": "claude-test",
                            "api_key_env": "ANTHROPIC_API_KEY",
                            "version": "2023-06-01",
                        },
                    }
                ),
                encoding="utf-8",
            )
            resolved = load_and_resolve_agent_profile(profile_path)

        self.assertEqual(resolved["agent_profile_name"], "claude-sonnet")
        self.assertEqual(
            resolved["code_agent_ref"],
            "acbench.agents.anthropic_code:AnthropicCodePatchAgent",
        )
        self.assertEqual(
            resolved["aiops_agent_ref"],
            "acbench.agents.anthropic_ops:AnthropicOpsAgent",
        )
        self.assertEqual(resolved["code_agent_config"]["model"], "claude-test")
        self.assertEqual(resolved["ops_agent_config"]["version"], "2023-06-01")

    def test_load_and_resolve_azure_openai_profile_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile_path = Path(tmp_dir) / "azure.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "name": "azure-openai",
                        "code": {
                            "provider": "azure_openai",
                            "model": "gpt-4.1-mini",
                            "api_key_env": "AZURE_OPENAI_API_KEY",
                            "base_url": "https://example.openai.azure.com/openai/v1/",
                        },
                        "ops": {
                            "provider": "azure_openai",
                            "model": "gpt-4.1-mini",
                            "api_key_env": "AZURE_OPENAI_API_KEY",
                            "base_url": "https://example.openai.azure.com/openai/v1/",
                        },
                    }
                ),
                encoding="utf-8",
            )
            resolved = load_and_resolve_agent_profile(profile_path)

        self.assertEqual(
            resolved["code_agent_ref"],
            "acbench.agents.azure_openai_code:AzureOpenAICodePatchAgent",
        )
        self.assertEqual(
            resolved["aiops_agent_ref"],
            "acbench.agents.azure_openai_ops:AzureOpenAIOpsAgent",
        )
        self.assertEqual(resolved["code_agent_config"]["provider"], "azure_openai")
        self.assertEqual(resolved["ops_agent_config"]["provider"], "azure_openai")

    def test_apply_agent_profile_to_payload_merges_agent_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile_path = Path(tmp_dir) / "custom.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "name": "custom-agent",
                        "code": {
                            "provider": "custom",
                            "agent_ref": "tests.test_standalone_code_executor:FakePatchAgent",
                        },
                    }
                ),
                encoding="utf-8",
            )
            payload = apply_agent_profile_to_payload(
                {
                    "agent_config": str(profile_path),
                    "max_steps": 12,
                }
            )

        self.assertEqual(payload["agent_profile_name"], "custom-agent")
        self.assertEqual(
            payload["code_agent_ref"],
            "tests.test_standalone_code_executor:FakePatchAgent",
        )
        self.assertEqual(payload["max_steps"], 12)


if __name__ == "__main__":
    unittest.main()
