"""Minimal prompt-overlay reproduction for aggregator-backed GPT-5 models."""

from __future__ import annotations


GPT5_OVERLAY = "\n".join(
    [
        "## Interaction Style",
        "## GPT-5 Output Contract",
        "## Execution Bias",
    ]
)


def resolve_system_prompt_contribution(provider_id: str, model_id: str) -> str | None:
    """Return the GPT-5 overlay when it applies to the current provider."""

    if provider_id != "openai":
        return None
    if not model_id.startswith("gpt-5"):
        return None
    return GPT5_OVERLAY
