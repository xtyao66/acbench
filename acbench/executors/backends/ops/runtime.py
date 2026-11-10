"""Internal runtime models for future ACBench-owned ops backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from acbench.models.result import ExecutorResult
from acbench.models.result import _json_safe
from acbench.models.scenario import ScenarioSpec


@dataclass(slots=True)
class NativeOpsProblem:
    """Normalized ops-task description used by internal ACBench backends."""

    problem_id: str
    source: str
    application: str
    service: str
    description: str = ""
    deployment: str = "k8s"
    task_summary: str = ""
    task_instructions: str = ""
    acceptance_notes: str = ""
    issue_text: str = ""
    error_logs: list[str] = field(default_factory=list)
    reproduction_steps: list[str] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)
    visible_notes: str = ""
    require_detection: bool = False
    require_localization: bool = False
    require_repair: bool = False
    detection_keywords: list[str] = field(default_factory=list)
    localization_keywords: list[str] = field(default_factory=list)
    repair_keywords: list[str] = field(default_factory=list)

    @classmethod
    def from_scenario(cls, scenario: ScenarioSpec) -> "NativeOpsProblem":
        """Build one normalized ops problem from a scenario."""

        if scenario.ops_fault is None:
            raise ValueError(f"Scenario {scenario.scenario_id} does not contain an ops fault.")
        return cls(
            problem_id=scenario.ops_fault.problem_id,
            source=scenario.ops_fault.source,
            application=scenario.service.application,
            service=scenario.service.service,
            description=scenario.ops_fault.description,
            deployment=scenario.service.deployment,
            task_summary=scenario.task.summary,
            task_instructions=scenario.task.instructions,
            acceptance_notes=scenario.task.acceptance_notes,
            issue_text=scenario.visible_context.issue_text,
            error_logs=list(scenario.visible_context.error_logs),
            reproduction_steps=list(scenario.visible_context.reproduction_steps),
            relevant_files=list(scenario.visible_context.relevant_files),
            visible_notes=scenario.visible_context.notes,
            require_detection=scenario.success_criteria.require_detection,
            require_localization=scenario.success_criteria.require_localization,
            require_repair=scenario.success_criteria.require_repair,
            detection_keywords=list(scenario.ops_fault.detection_keywords),
            localization_keywords=list(scenario.ops_fault.localization_keywords),
            repair_keywords=list(scenario.ops_fault.repair_keywords),
        )


@dataclass(slots=True)
class OpsRunRequest:
    """Execution request for one internal ops backend run."""

    problem: NativeOpsProblem
    output_dir: Path
    max_steps: int = 10
    agent_ref: str = ""
    keep_artifacts: bool = True
    allow_synthetic_ops: bool = False
    ops_agent_config: dict[str, object] = field(default_factory=dict)
    openai_model: str = ""
    openai_api_key_env: str = "OPENAI_API_KEY"
    openai_base_url: str = ""
    anthropic_model: str = ""
    anthropic_api_key_env: str = "ANTHROPIC_API_KEY"
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_version: str = "2023-06-01"


@dataclass(slots=True)
class OpsRunOutcome:
    """Normalized result produced by an internal ops backend run."""

    detected: bool = False
    localized: bool = False
    repaired: bool = False
    success: bool = False
    metrics: dict[str, object] = field(default_factory=dict)
    logs: dict[str, str] = field(default_factory=dict)
    details: dict[str, object] = field(default_factory=dict)

    def to_executor_payload(self, backend_name: str) -> dict[str, object]:
        """Convert the outcome into a stable executor-like payload."""

        return {
            "backend": backend_name,
            "success": self.success,
            "detected": self.detected,
            "localized": self.localized,
            "repaired": self.repaired,
            "metrics": _json_safe(dict(self.metrics)),
            "logs": _json_safe(dict(self.logs)),
            "details": _json_safe(dict(self.details)),
        }

    def to_executor_result(self, backend_name: str) -> ExecutorResult:
        """Convert the outcome into a normalized executor result."""

        return ExecutorResult(
            backend=backend_name,
            success=self.success,
            detected=self.detected,
            localized=self.localized,
            repaired=self.repaired,
            metrics=_json_safe(dict(self.metrics)),
            logs=_json_safe(dict(self.logs)),
            details=_json_safe(dict(self.details)),
        )
