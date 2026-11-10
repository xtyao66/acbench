"""Scenario-level readiness checks for standalone ACBench."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from acbench.models.scenario import ScenarioSpec
from acbench.orchestrator.doctor import inspect_acbench_code_backend
from acbench.paths import resolve_repo_path


@dataclass(slots=True)
class ReadinessIssue:
    """One readiness issue detected for a scenario."""

    level: str
    source: str
    message: str


@dataclass(slots=True)
class ScenarioReadinessReport:
    """Readiness report for a scenario under the current environment."""

    scenario_id: str
    ready_for_dry_run: bool
    ready_for_live_run: bool
    issues: list[ReadinessIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "ready_for_dry_run": self.ready_for_dry_run,
            "ready_for_live_run": self.ready_for_live_run,
            "issues": [asdict(issue) for issue in self.issues],
        }


def check_scenario_readiness(scenario: ScenarioSpec) -> ScenarioReadinessReport:
    """Check whether a scenario is runnable under the current environment."""

    issues: list[ReadinessIssue] = []

    # ops_fault.source is a free-form provenance identifier (third-party task
    # packs use their own); the local ops executor runs any source, so it is
    # deliberately not a readiness condition.

    if scenario.mode in {"code_only", "combined"}:
        if scenario.service.repository_path:
            repo_path = resolve_repo_path(scenario.service.repository_path)
            if not repo_path.exists():
                issues.append(
                    ReadinessIssue(
                        level="error",
                        source="scenario",
                        message=f"Repository path does not exist: {repo_path}",
                    )
                )
        elif scenario.source.type == "github":
            issues.append(
                ReadinessIssue(
                    level="error",
                    source="scenario",
                    message=(
                        "GitHub-backed scenario is pinned correctly but does not yet have "
                        "a local repository_path materialized for live execution."
                    ),
                )
            )
        else:
            issues.append(
                ReadinessIssue(
                    level="warning",
                    source="scenario",
                    message="repository_path is not set for a code-capable scenario.",
                )
            )

        if not scenario.build.test_cmds:
            issues.append(
                ReadinessIssue(
                    level="warning",
                    source="scenario",
                    message="No test_cmds defined for code scenario.",
                )
            )

        acbench_code = inspect_acbench_code_backend()
        git_present = any(
            check.name == "git" and check.available
            for check in acbench_code.recommended_commands
        )
        if not git_present:
            issues.append(
                ReadinessIssue(
                    level="warning",
                    source="acbench-code",
                    message="git is not available; standalone code runs can still work, but diff capture may be limited.",
                )
            )

    ready_for_dry_run = not any(issue.level == "error" and issue.source == "scenario" for issue in issues)
    ready_for_live_run = not any(issue.level == "error" for issue in issues)
    return ScenarioReadinessReport(
        scenario_id=scenario.scenario_id,
        ready_for_dry_run=ready_for_dry_run,
        ready_for_live_run=ready_for_live_run,
        issues=issues,
    )
