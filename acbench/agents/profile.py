"""Generic agent profile loading for benchmark runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from acbench.paths import resolve_repo_path


_PROVIDER_DEFAULTS: dict[str, dict[str, dict[str, str]]] = {
    "openai": {
        "code": {
            "agent_ref": "acbench.agents.openai_code:OpenAICodePatchAgent",
        },
        "ops": {
            "agent_ref": "acbench.agents.openai_ops:OpenAIOpsAgent",
        },
    },
    "anthropic": {
        "code": {
            "agent_ref": "acbench.agents.anthropic_code:AnthropicCodePatchAgent",
        },
        "ops": {
            "agent_ref": "acbench.agents.anthropic_ops:AnthropicOpsAgent",
        },
    },
    "azure_openai": {
        "code": {
            "agent_ref": "acbench.agents.azure_openai_code:AzureOpenAICodePatchAgent",
        },
        "ops": {
            "agent_ref": "acbench.agents.azure_openai_ops:AzureOpenAIOpsAgent",
        },
    },
    "openai_compatible": {
        "code": {
            "agent_ref": "acbench.agents.openai_code:OpenAICodePatchAgent",
        },
        "ops": {
            "agent_ref": "acbench.agents.openai_ops:OpenAIOpsAgent",
        },
    },
}


def load_agent_profile(profile_path: str | Path) -> dict[str, Any]:
    """Load one JSON agent profile from disk."""

    path = resolve_repo_path(profile_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Agent profile must be a JSON object.")
    return payload


def resolve_agent_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Convert one generic agent profile into RunConfig-compatible fields."""

    resolved: dict[str, Any] = {
        "agent_profile_name": str(profile.get("name", "")).strip(),
        "code_agent_config": {},
        "ops_agent_config": {},
    }
    code_section = profile.get("code")
    ops_section = profile.get("ops")
    if code_section is not None:
        if not isinstance(code_section, dict):
            raise ValueError("`code` section in agent profile must be an object.")
        resolved.update(_resolve_section(code_section, role="code"))
    if ops_section is not None:
        if not isinstance(ops_section, dict):
            raise ValueError("`ops` section in agent profile must be an object.")
        resolved.update(_resolve_section(ops_section, role="ops"))
    if not resolved.get("code_agent_ref") and not resolved.get("aiops_agent_ref"):
        raise ValueError("Agent profile must define at least one of `code` or `ops`.")
    return resolved


def load_and_resolve_agent_profile(profile_path: str | Path) -> dict[str, Any]:
    """Load one agent profile file and resolve it into runtime config fields."""

    resolved = resolve_agent_profile(load_agent_profile(profile_path))
    resolved["agent_config_path"] = str(resolve_repo_path(profile_path))
    return resolved


def apply_agent_profile_to_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge an optional `agent_config` path into one prediction/config payload."""

    profile_path = payload.get("agent_config")
    if not profile_path:
        return dict(payload)
    merged = load_and_resolve_agent_profile(str(profile_path))
    merged.update(payload)
    return merged


def _resolve_section(section: dict[str, Any], *, role: str) -> dict[str, Any]:
    provider = str(section.get("provider", "")).strip().lower()
    agent_ref = str(section.get("agent_ref", "")).strip()
    if not agent_ref:
        if provider not in _PROVIDER_DEFAULTS:
            raise ValueError(
                f"Unsupported provider `{provider}` for `{role}`. "
                "Use a known provider or set `agent_ref` explicitly."
            )
        agent_ref = _PROVIDER_DEFAULTS[provider][role]["agent_ref"]

    config = dict(section)
    config.setdefault("provider", provider)
    config.setdefault("role", role)

    resolved: dict[str, Any] = {}
    if role == "code":
        resolved["code_agent_ref"] = agent_ref
        resolved["code_agent_config"] = config
    else:
        resolved["aiops_agent_ref"] = agent_ref
        resolved["ops_agent_config"] = config
    return resolved
