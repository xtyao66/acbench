"""Execution adapters for the internal standalone ACBench ops runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from acbench.agents.loader import load_object
from acbench.executors.backends.ops.rubric import (
    DEFAULT_PASS_THRESHOLD,
    evaluate_problem,
)
from acbench.executors.backends.ops.runtime import (
    NativeOpsProblem,
    OpsRunOutcome,
    OpsRunRequest,
)


class OpsRuntimeEngine(Protocol):
    """Protocol for pluggable ACBench ops runtime engines."""

    def run(self, request: OpsRunRequest) -> OpsRunOutcome:
        """Execute one ops-task request and return a normalized outcome."""


@dataclass(slots=True)
class StandaloneLocalOpsEngine:
    """ACBench-owned synthetic ops engine for local development and demos."""

    def run(self, request: OpsRunRequest) -> OpsRunOutcome:
        """Produce a synthetic ops outcome, or a not-evaluated placeholder.

        With no ops agent configured, the default is to report the stage as NOT
        evaluated (no credit) instead of silently auto-passing it. Passing
        ``allow_synthetic_ops`` opts into the optimistic synthetic placeholder,
        which is intended for demos and pipeline smoke tests only.
        """

        problem = request.problem
        if not request.allow_synthetic_ops:
            return OpsRunOutcome(
                detected=False,
                localized=False,
                repaired=False,
                success=False,
                metrics={
                    "TTD": 0.0,
                    "TTL": 0.0,
                    "TTM": 0.0,
                    "synthetic": True,
                    "evaluated": False,
                },
                details={
                    "mode": "ops-not-evaluated",
                    "problem_id": problem.problem_id,
                    "max_steps": request.max_steps,
                    "agent_ref": request.agent_ref,
                    "note": (
                        "No ops agent configured; this stage was not evaluated and "
                        "earns no credit. Pass --aiops-agent-ref to evaluate with an "
                        "agent, or --allow-synthetic-ops for a synthetic placeholder."
                    ),
                },
            )

        metrics = {
            "TTD": 1.0 if problem.require_detection else 0.0,
            "TTL": 2.0 if problem.require_localization else 0.0,
            "TTM": 3.0 if problem.require_repair else 0.0,
            "synthetic": True,
            "evaluated": False,
        }
        return OpsRunOutcome(
            detected=problem.require_detection,
            localized=problem.require_localization,
            repaired=problem.require_repair,
            success=True,
            metrics=metrics,
            details={
                "mode": "synthetic-local-ops",
                "synthetic_opt_in": True,
                "problem_id": problem.problem_id,
                "max_steps": request.max_steps,
                "agent_ref": request.agent_ref,
            },
        )


@dataclass(slots=True)
class AgentDrivenOpsEngine:
    """Run one ops task through a configured agent and score it with a rubric."""

    def run(self, request: OpsRunRequest) -> OpsRunOutcome:
        agent_cls = load_object(request.agent_ref)
        agent = agent_cls()
        if hasattr(agent, "configure"):
            agent.configure(
                run_config=request,
                model=request.openai_model,
                api_key_env=request.openai_api_key_env,
                base_url=request.openai_base_url,
                anthropic_model=request.anthropic_model,
                anthropic_api_key_env=request.anthropic_api_key_env,
                anthropic_base_url=request.anthropic_base_url,
                anthropic_version=request.anthropic_version,
            )
        if not hasattr(agent, "analyze"):
            raise ValueError(
                f"Configured ops agent `{request.agent_ref}` does not expose `analyze`."
            )

        artifacts = agent.analyze(
            request.problem,
            output_dir=request.output_dir,
        )
        assessment = dict(artifacts.get("assessment", {}))

        # Grade each stage on discriminative (non-leaked) keyword recall. The
        # agent's own self-reported booleans are deliberately NOT part of the
        # pass decision — they are retained only as telemetry below.
        rubric = evaluate_problem(request.problem, assessment, threshold=DEFAULT_PASS_THRESHOLD)
        detection = rubric["detection"]
        localization = rubric["localization"]
        remediation = rubric["remediation"]

        # A stage with no gradeable signal (every keyword leaked into the prompt)
        # earns no credit and does not count as success: its flag stays False
        # and scoring.py excludes it from the score. Success needs every
        # gradeable required stage to pass, and at least one such stage, so an
        # empty answer cannot succeed on a scenario whose stages are all leaked.
        def _stage_ok(report, required: bool) -> bool:
            if not required:
                return True
            return report.gradeable and report.passed

        detected = _stage_ok(detection, request.problem.require_detection)
        localized = _stage_ok(localization, request.problem.require_localization)
        repaired = _stage_ok(remediation, request.problem.require_repair)
        required_reports = [
            report
            for report, required in (
                (detection, request.problem.require_detection),
                (localization, request.problem.require_localization),
                (remediation, request.problem.require_repair),
            )
            if required
        ]
        graded_reports = [report for report in required_reports if report.gradeable]
        success = all(report.passed for report in graded_reports) and (
            bool(graded_reports) or not required_reports
        )

        return OpsRunOutcome(
            detected=detected,
            localized=localized,
            repaired=repaired,
            success=success,
            metrics={
                "TTD": 1.0 if detected else 0.0,
                "TTL": 2.0 if localized else 0.0,
                "TTM": 3.0 if repaired else 0.0,
                "synthetic": False,
                "agent_ref": request.agent_ref,
                "rubric_detection_recall": round(detection.recall, 6),
                "rubric_localization_recall": round(localization.recall, 6),
                "rubric_remediation_recall": round(remediation.recall, 6),
                "rubric_detection_graded_on": detection.graded_on,
                "rubric_localization_graded_on": localization.graded_on,
                "rubric_remediation_graded_on": remediation.graded_on,
                # The model's own claims, kept ONLY as telemetry — never graded.
                "self_reported_detected": bool(assessment.get("detected", False)),
                "self_reported_localized": bool(assessment.get("localized", False)),
                "self_reported_repaired": bool(assessment.get("repaired", False)),
                "agent_answer_count": int(artifacts.get("telemetry", {}).get("answer_count", 0)),
                "agent_answer_durations_seconds": list(
                    artifacts.get("telemetry", {}).get("answer_durations_seconds", [])
                ),
                "agent_total_answer_seconds": float(
                    artifacts.get("telemetry", {}).get("total_answer_seconds", 0.0)
                ),
                "agent_average_answer_seconds": float(
                    artifacts.get("telemetry", {}).get("average_answer_seconds", 0.0)
                ),
                "agent_wall_time_seconds": float(
                    artifacts.get("telemetry", {}).get("wall_time_seconds", 0.0)
                ),
            },
            logs={
                "prompt_path": str(artifacts.get("prompt_path", "")),
                "response_path": str(artifacts.get("response_path", "")),
                "assessment_path": str(artifacts.get("assessment_path", "")),
                "agent_telemetry_path": str(artifacts.get("telemetry_path", "")),
            },
            details={
                "mode": "agent-driven-ops",
                "problem_id": request.problem.problem_id,
                "max_steps": request.max_steps,
                "agent_ref": request.agent_ref,
                "assessment": assessment,
                "agent_telemetry": artifacts.get("telemetry", {}),
                "rubric": {stage: report.to_dict() for stage, report in rubric.items()},
                "matched_detection_keywords": list(detection.matched),
                "matched_localization_keywords": list(localization.matched),
                "matched_repair_keywords": list(remediation.matched),
            },
        )


def build_default_engine() -> OpsRuntimeEngine:
    """Build the default standalone ops runtime engine."""

    return StandaloneLocalOpsEngine()


def build_engine_for_problem(problem: NativeOpsProblem) -> OpsRuntimeEngine:
    """Build the most appropriate current engine for one ops problem."""

    return build_default_engine()


def build_engine_for_request(request: OpsRunRequest) -> OpsRuntimeEngine:
    """Select the best engine for one normalized ops request."""

    if request.agent_ref:
        return AgentDrivenOpsEngine()
    return build_engine_for_problem(request.problem)
