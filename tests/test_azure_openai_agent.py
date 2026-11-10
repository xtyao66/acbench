"""Tests for Azure OpenAI agent wrappers."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from acbench.agents.azure_openai_code import AzureOpenAICodePatchAgent
from acbench.agents.azure_openai_ops import AzureOpenAIOpsAgent
from acbench.models.runtime import RunConfig


class AzureOpenAICodePatchAgentTests(unittest.TestCase):
    def test_generate_patch_requires_model(self) -> None:
        agent = AzureOpenAICodePatchAgent()
        run_config = RunConfig(code_agent_config={"base_url": "https://example.openai.azure.com/openai/v1/"})

        with self.assertRaisesRegex(ValueError, "requires `code.model`"):
            agent.generate_patch(object(), run_config, output_dir=Path("."))

    def test_generate_patch_requires_base_url(self) -> None:
        agent = AzureOpenAICodePatchAgent()
        run_config = RunConfig(code_agent_config={"model": "gpt-4.1-mini"})

        with self.assertRaisesRegex(ValueError, "requires `code.base_url`"):
            agent.generate_patch(object(), run_config, output_dir=Path("."))

    def test_generate_patch_uses_azure_defaults_and_overrides(self) -> None:
        agent = AzureOpenAICodePatchAgent()
        run_config = RunConfig(
            openai_model="fallback-model",
            openai_api_key_env="FALLBACK_KEY",
            openai_base_url="https://fallback.invalid/openai/v1/",
            code_agent_config={
                "model": "azure-model",
                "base_url": "https://example.openai.azure.com/openai/v1/",
            },
        )

        with patch("acbench.agents.openai_code.OpenAICodePatchAgent.generate_patch", return_value="ok") as mock_generate:
            result = agent.generate_patch(object(), run_config, output_dir=Path("out"))

        self.assertEqual(result, "ok")
        forwarded_config = mock_generate.call_args.args[1]
        self.assertEqual(forwarded_config.openai_model, "azure-model")
        self.assertEqual(forwarded_config.openai_api_key_env, "AZURE_OPENAI_API_KEY")
        self.assertEqual(forwarded_config.openai_base_url, "https://example.openai.azure.com/openai/v1/")


class AzureOpenAIOpsAgentTests(unittest.TestCase):
    def test_configure_uses_azure_key_env_by_default(self) -> None:
        agent = AzureOpenAIOpsAgent()
        run_config = RunConfig(
            openai_model="azure-model-from-run-config",
            openai_api_key_env="AZURE_RUN_CONFIG_KEY",
            openai_base_url="https://example.openai.azure.com/openai/v1/",
        )

        with patch("acbench.agents.openai_ops.OpenAIOpsAgent.configure") as mock_configure:
            agent.configure(run_config)

        self.assertEqual(
            mock_configure.call_args.kwargs["model"],
            "azure-model-from-run-config",
        )
        self.assertEqual(mock_configure.call_args.kwargs["api_key_env"], "AZURE_OPENAI_API_KEY")
        self.assertEqual(
            mock_configure.call_args.kwargs["base_url"],
            "https://example.openai.azure.com/openai/v1/",
        )

    def test_configure_requires_model(self) -> None:
        agent = AzureOpenAIOpsAgent()

        with self.assertRaisesRegex(ValueError, "requires `ops.model`"):
            agent.configure(RunConfig(ops_agent_config={"base_url": "https://example.openai.azure.com/openai/v1/"}))

    def test_configure_requires_base_url(self) -> None:
        agent = AzureOpenAIOpsAgent()

        with self.assertRaisesRegex(ValueError, "requires `ops.base_url`"):
            agent.configure(RunConfig(ops_agent_config={"model": "azure-model"}))

    def test_configure_passes_azure_values_to_openai_ops_agent(self) -> None:
        agent = AzureOpenAIOpsAgent()
        run_config = RunConfig(
            ops_agent_config={
                "model": "azure-model",
                "api_key_env": "AZURE_CUSTOM_KEY",
                "base_url": "https://example.openai.azure.com/openai/v1/",
            }
        )

        with patch("acbench.agents.openai_ops.OpenAIOpsAgent.configure") as mock_configure:
            agent.configure(run_config)

        self.assertEqual(mock_configure.call_args.kwargs["model"], "azure-model")
        self.assertEqual(mock_configure.call_args.kwargs["api_key_env"], "AZURE_CUSTOM_KEY")
        self.assertEqual(mock_configure.call_args.kwargs["base_url"], "https://example.openai.azure.com/openai/v1/")


if __name__ == "__main__":
    unittest.main()
