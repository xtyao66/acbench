"""Azure OpenAI-backed code agent integration for ACBench."""

from __future__ import annotations

from dataclasses import replace

from acbench.agents.openai_code import OpenAICodePatchAgent
from acbench.models.runtime import RunConfig


def _contains_placeholder(value: str) -> bool:
    """Return whether one Azure config field still contains template markers."""

    return "<" in value or ">" in value


class AzureOpenAICodePatchAgent(OpenAICodePatchAgent):
    """OpenAI-compatible code agent configured for Azure OpenAI credentials."""

    def generate_patch(
        self, 
        scenario, 
        run_config: RunConfig, 
        *, 
        output_dir
        ):
        section = dict(run_config.code_agent_config or {})
        model = str(section.get("model", run_config.openai_model)).strip()
        api_key_env = str(
            section.get(
                "api_key_env", 
                "AZURE_OPENAI_API_KEY"
            )
        ).strip()
        base_url = str(section.get("base_url", run_config.openai_base_url or "")).strip()

        if not model:
            raise ValueError(
                "AzureOpenAICodePatchAgent requires `code.model` set to your Azure deployment name."
            )
        if _contains_placeholder(model):
            raise ValueError(
                "AzureOpenAICodePatchAgent `code.model` still contains a placeholder. "
                "Replace `<your deployment name>` with your actual Azure deployment name."
            )
        if not base_url:
            raise ValueError(
                "AzureOpenAICodePatchAgent requires `code.base_url` (for example `https://<resource>.openai.azure.com/openai/v1/`)."
            )
        if _contains_placeholder(base_url):
            raise ValueError(
                "AzureOpenAICodePatchAgent `code.base_url` still contains a placeholder. "
                "Replace `<resource>` with your actual Azure resource host."
            )

        azure_run_config = replace(
            run_config,
            openai_model=model,
            openai_api_key_env=api_key_env,
            openai_base_url=base_url,
            code_agent_config=section,
        )
        return super().generate_patch(scenario, azure_run_config, output_dir=output_dir)
