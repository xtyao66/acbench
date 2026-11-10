"""Scenario models for the ACBench."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Literal


ScenarioMode = Literal["ops_only", "code_only", "combined"]
ScenarioSourceType = Literal["local_fixture", "github"]


@dataclass(slots=True)
class ServiceSpec:
    """Target application and service selection."""

    application: str
    service: str
    deployment: str = "k8s"
    repository_path: str | None = None


@dataclass(slots=True)
class ScenarioSourceSpec:
    """Where the benchmark task originates from."""

    type: ScenarioSourceType = "local_fixture"
    repo_url: str = ""
    base_commit: str = ""
    issue_url: str = ""
    pr_url: str = ""
    snapshot_key: str = ""
    license_note: str = ""


@dataclass(slots=True)
class TaskSpec:
    """User-facing task framing for the agent."""

    summary: str = ""
    instructions: str = ""
    acceptance_notes: str = ""


@dataclass(slots=True)
class VisibleContextSpec:
    """Context intentionally exposed to the agent."""

    issue_text: str = ""
    error_logs: list[str] = field(default_factory=list)
    reproduction_steps: list[str] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass(slots=True)
class OpsFaultSpec:
    """Operational incident configuration."""

    source: str
    problem_id: str
    description: str = ""
    detection_keywords: list[str] = field(default_factory=list)
    localization_keywords: list[str] = field(default_factory=list)
    repair_keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CodeFaultSpec:
    """Code-level defect configuration."""

    source: str
    defect_id: str
    description: str = ""
    target_files: list[str] = field(default_factory=list)
    instance_path: str = ""
    platform: str = "windows"


@dataclass(slots=True)
class BuildSpec:
    """Repository build and test commands."""

    rebuild_cmds: list[str] = field(default_factory=list)
    test_cmds: list[str] = field(default_factory=list)
    print_cmds: list[str] = field(default_factory=list)
    log_parser: str = ""
    # Execution language for the code stage. Selects the test backend /
    # output parser ("python" -> pytest+unittest, "go" -> ``go test -json``).
    # Defaults to "python" so every existing scenario keeps its behavior.
    language: str = "python"


@dataclass(slots=True)
class EnvironmentSpec:
    """Environment preparation that sits alongside build/test commands."""

    setup_cmds: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    working_directory: str = ""
    requires_container: bool = False


@dataclass(slots=True)
class SuccessCriteria:
    """Run success requirements."""

    require_detection: bool = False
    require_localization: bool = False
    require_repair: bool = False
    require_build_success: bool = False
    require_test_success: bool = False
    require_deploy_success: bool = False


@dataclass(slots=True)
class EvaluationSpec:
    """How the scenario should be evaluated."""

    strategy: str = "behavioral"
    fail_to_pass: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)
    required_tests: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    allow_alternative_fixes: bool = True
    # Optional measured-performance spec for perf scenarios (bench_cmd, metric,
    # reduction, reps, warmup, speedup_formula, gold_speedup); ignored by the
    # correctness oracle and graded by the measured-speedup harness.
    perf: dict | None = None


@dataclass(slots=True)
class ConstraintSpec:
    """Execution constraints and policy bounds."""

    allow_network: bool = False
    allow_test_changes: bool = False
    max_runtime_minutes: int = 30
    max_agent_steps: int = 0
    notes: str = ""


@dataclass(slots=True)
class MetadataSpec:
    """Authoring metadata that helps curate the task bank."""

    difficulty: str = ""
    language: str = ""
    framework: str = ""
    categories: list[str] = field(default_factory=list)
    source_benchmark: str = ""


@dataclass(slots=True)
class ScenarioSpec:
    """Unified scenario format for ACBench."""

    scenario_id: str
    title: str
    mode: ScenarioMode
    service: ServiceSpec
    source: ScenarioSourceSpec = field(default_factory=ScenarioSourceSpec)
    task: TaskSpec = field(default_factory=TaskSpec)
    visible_context: VisibleContextSpec = field(default_factory=VisibleContextSpec)
    ops_fault: OpsFaultSpec | None = None
    code_fault: CodeFaultSpec | None = None
    environment: EnvironmentSpec = field(default_factory=EnvironmentSpec)
    build: BuildSpec = field(default_factory=BuildSpec)
    success_criteria: SuccessCriteria = field(default_factory=SuccessCriteria)
    evaluation: EvaluationSpec = field(default_factory=EvaluationSpec)
    constraints: ConstraintSpec = field(default_factory=ConstraintSpec)
    metadata: MetadataSpec = field(default_factory=MetadataSpec)
    metrics: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    gold_patch_path: str = ""
    schema_version: str = "1.0"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScenarioSpec":
        source = ScenarioSourceSpec(**data.get("source", {}))
        service = ServiceSpec(**data["service"])
        task = TaskSpec(**data.get("task", {}))
        visible_context = VisibleContextSpec(**data.get("visible_context", {}))
        ops_fault = OpsFaultSpec(**data["ops_fault"]) if data.get("ops_fault") else None
        code_fault = (
            CodeFaultSpec(**data["code_fault"]) if data.get("code_fault") else None
        )
        environment = EnvironmentSpec(**data.get("environment", {}))
        build = BuildSpec(**data.get("build", {}))
        success_criteria = SuccessCriteria(**data.get("success_criteria", {}))
        evaluation = EvaluationSpec(**data.get("evaluation", {}))
        constraints = ConstraintSpec(**data.get("constraints", {}))
        metadata = MetadataSpec(**data.get("metadata", {}))
        scenario = cls(
            scenario_id=data["scenario_id"],
            title=data["title"],
            mode=data["mode"],
            source=source,
            service=service,
            task=task,
            visible_context=visible_context,
            ops_fault=ops_fault,
            code_fault=code_fault,
            environment=environment,
            build=build,
            success_criteria=success_criteria,
            evaluation=evaluation,
            constraints=constraints,
            metadata=metadata,
            metrics=list(data.get("metrics", [])),
            tags=list(data.get("tags", [])),
            notes=data.get("notes", ""),
            gold_patch_path=data.get("gold_patch_path", ""),
            schema_version=str(data.get("schema_version", "1.0")),
        )
        scenario.validate()
        return scenario

    @classmethod
    def from_file(cls, path: str | Path) -> "ScenarioSpec":
        scenario_path = Path(path)
        with scenario_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return cls.from_dict(data)

    def validate(self) -> None:
        if self.mode not in {"ops_only", "code_only", "combined"}:
            raise ValueError(f"Unsupported scenario mode: {self.mode}")

        if self.source.type not in {"local_fixture", "github"}:
            raise ValueError(f"Unsupported scenario source type: {self.source.type}")

        if self.source.type == "github":
            if not self.source.repo_url:
                raise ValueError("github scenarios require source.repo_url")
            if not self.source.base_commit:
                raise ValueError("github scenarios require source.base_commit")

        if self.mode in {"ops_only", "combined"} and self.ops_fault is None:
            raise ValueError("ops_fault is required for ops_only and combined scenarios")

        if self.mode in {"code_only", "combined"} and self.code_fault is None:
            raise ValueError("code_fault is required for code_only and combined scenarios")

        # The fault `source` is a free-form provenance identifier (e.g. "acbench",
        # or a third-party task pack's name). It must be declared, but is NOT
        # gated to "acbench" — external task packs are first-class as long as they
        # satisfy the structural format below. Execution compatibility (can a
        # given backend run this source?) is the executor's concern, not the
        # schema's.
        if self.mode in {"ops_only", "combined"} and self.ops_fault is not None:
            if not str(self.ops_fault.source).strip():
                raise ValueError("ops_fault.source must be a non-empty identifier")

        if self.mode in {"code_only", "combined"} and self.code_fault is not None:
            if not str(self.code_fault.source).strip():
                raise ValueError("code_fault.source must be a non-empty identifier")
            if not self.build.rebuild_cmds and not self.build.test_cmds:
                raise ValueError(
                    "code_only and combined scenarios require rebuild_cmds or test_cmds"
                )
            if self.source.type == "local_fixture" and not self.service.repository_path:
                raise ValueError(
                    "local_fixture code scenarios require service.repository_path"
                )

        if self.metadata.difficulty and self.metadata.difficulty not in {
            "easy",
            "medium",
            "hard",
            "expert",
        }:
            raise ValueError(
                "metadata.difficulty must be one of easy, medium, hard, expert"
            )

        if self.constraints.max_runtime_minutes < 0:
            raise ValueError("constraints.max_runtime_minutes must be non-negative")

        if self.constraints.max_agent_steps < 0:
            raise ValueError("constraints.max_agent_steps must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
