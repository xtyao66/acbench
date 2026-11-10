"""Runtime configuration models for the ACBench."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RunConfig:
    """Top-level run configuration passed into executors."""

    dry_run: bool = False
    max_steps: int = 10
    keep_artifacts: bool = True
    # When no ops agent is configured, do NOT silently auto-pass ops stages.
    # Set True only to opt into the synthetic placeholder (demos / pipeline
    # smoke tests); by default a no-agent ops stage is reported as not evaluated.
    allow_synthetic_ops: bool = False
    aiops_agent_type: str = "unconfigured"
    code_agent_type: str = "unconfigured"
    aiops_agent_ref: str = ""
    code_agent_ref: str = ""
    agent_config_path: str = ""
    agent_profile_name: str = ""
    code_agent_config: dict[str, Any] = field(default_factory=dict)
    ops_agent_config: dict[str, Any] = field(default_factory=dict)
    code_patch_path: str = ""
    openai_model: str = ""
    openai_api_key_env: str = "OPENAI_API_KEY"
    openai_base_url: str = ""
    anthropic_model: str = ""
    anthropic_api_key_env: str = "ANTHROPIC_API_KEY"
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_version: str = "2023-06-01"
    # In combined mode the runner populates this with the ops-stage diagnosis so
    # the code-repair stage is informed by it (end-to-end coupling).
    upstream_ops_diagnosis: dict[str, Any] | None = None
    # Ablation switch: when True, the ops diagnosis is NOT threaded into the code
    # stage, so combined runs as two independent stages. Used to measure the
    # effect of the coupling (combined-with-coupling vs. independent).
    disable_coupling: bool = False
    # Experiment switch: when True, the code prompt does NOT identify the faulty
    # file (all source is shown unlabeled), so the diagnosis must provide the
    # localization. Used for the "is the diagnosis necessary" experiment.
    hide_fault_location: bool = False
