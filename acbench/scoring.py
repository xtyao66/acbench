"""Scenario scoring helpers for richer evaluation output."""

from __future__ import annotations

from typing import Any

from acbench.models.result import BenchmarkResult, ExecutorResult
from acbench.models.scenario import ScenarioSpec


CODE_COMPONENT_WEIGHTS = {
    "build": 0.15,
    "test": 0.15,
    "fail_to_pass": 0.45,
    "pass_to_pass": 0.25,
}

OPS_COMPONENT_WEIGHTS = {
    "detection": 0.30,
    "localization": 0.30,
    "remediation": 0.40,
}

COMBINED_STAGE_WEIGHTS = {
    "ops": 0.50,
    "code": 0.50,
}


def build_scorecard(
    scenario: ScenarioSpec,
    result: BenchmarkResult,
) -> dict[str, Any]:
    """Build a stable scorecard for one scenario result."""

    breakdown: dict[str, Any] = {}
    failure_reasons: list[str] = []
    # Only stages with at least one gradeable component get a score. A stage
    # that ran but has nothing gradeable (no required checks, or every required
    # check excluded as all-keywords-leaked) is left out of the overall score
    # instead of counting as 0.0 at full weight.
    stage_scores: dict[str, float] = {}

    if result.ops_result is not None:
        ops_score, ops_breakdown, ops_failures = _score_ops(
            scenario,
            result.ops_result,
        )
        if ops_score is not None:
            stage_scores["ops"] = ops_score
        breakdown["ops"] = ops_breakdown
        failure_reasons.extend(f"ops:{reason}" for reason in ops_failures)

    if result.code_result is not None:
        code_score, code_breakdown, code_failures = _score_code(
            scenario,
            result.code_result,
        )
        if code_score is not None:
            stage_scores["code"] = code_score
        breakdown["code"] = code_breakdown
        failure_reasons.extend(f"code:{reason}" for reason in code_failures)

    final_score, overall_breakdown = _score_overall(stage_scores)
    breakdown["overall"] = overall_breakdown
    gradeable = bool(stage_scores)

    if "ops" in stage_scores and "code" in stage_scores:
        code_details = result.code_result.details if result.code_result else {}
        breakdown["coupling"] = {
            "ops_diagnosis_provided": bool(code_details.get("ops_diagnosis_provided")),
            "diagnosis_localization_consistent": code_details.get(
                "diagnosis_localization_consistent"
            ),
        }

    return {
        # None when no stage had anything gradeable; aggregates must skip it.
        "final_score": _round(final_score) if gradeable else None,
        "ops_score": _reported_stage_score(stage_scores, "ops", result.ops_result),
        "code_score": _reported_stage_score(stage_scores, "code", result.code_result),
        "gradeable": gradeable,
        "score_breakdown": breakdown,
        "failure_reasons": _dedupe_keep_order(failure_reasons),
    }


def _reported_stage_score(
    stage_scores: dict[str, float],
    stage: str,
    stage_result: ExecutorResult | None,
) -> float | None:
    """Report a stage score: 0.0 if the stage did not run, None if it ran but was excluded."""

    if stage in stage_scores:
        return _round(stage_scores[stage])
    return None if stage_result is not None else 0.0


def _score_code(
    scenario: ScenarioSpec,
    result: ExecutorResult,
) -> tuple[float | None, dict[str, Any], list[str]]:
    weights: dict[str, float] = {}
    components: dict[str, float] = {}
    counts: dict[str, int] = {}
    failures: list[str] = []

    expected_fail_to_pass = len(scenario.evaluation.fail_to_pass)
    expected_pass_to_pass = len(scenario.evaluation.pass_to_pass)

    if scenario.success_criteria.require_build_success or scenario.build.rebuild_cmds:
        weights["build"] = CODE_COMPONENT_WEIGHTS["build"]
        components["build"] = 1.0 if result.build_success else 0.0
        if not result.build_success:
            failures.append("build_failed")

    if scenario.success_criteria.require_test_success or scenario.build.test_cmds:
        weights["test"] = CODE_COMPONENT_WEIGHTS["test"]
        components["test"] = 1.0 if result.test_success else 0.0
        if not result.test_success:
            failures.append("tests_failed")

    if expected_fail_to_pass:
        weights["fail_to_pass"] = CODE_COMPONENT_WEIGHTS["fail_to_pass"]
        components["fail_to_pass"] = _ratio(
            len(result.fail_to_pass_success),
            expected_fail_to_pass,
        )
        counts["fail_to_pass_expected"] = expected_fail_to_pass
        counts["fail_to_pass_success"] = len(result.fail_to_pass_success)
        counts["fail_to_pass_failure"] = len(result.fail_to_pass_failure)
        if result.fail_to_pass_failure:
            failures.append("fail_to_pass_incomplete")

    if expected_pass_to_pass:
        weights["pass_to_pass"] = CODE_COMPONENT_WEIGHTS["pass_to_pass"]
        components["pass_to_pass"] = _ratio(
            len(result.pass_to_pass_success),
            expected_pass_to_pass,
        )
        counts["pass_to_pass_expected"] = expected_pass_to_pass
        counts["pass_to_pass_success"] = len(result.pass_to_pass_success)
        counts["pass_to_pass_failure"] = len(result.pass_to_pass_failure)
        if result.pass_to_pass_failure:
            failures.append("pass_to_pass_regression")

    if result.details.get("apply_success") is False:
        failures.append("patch_apply_failed")

    # Build and pass_to_pass credit must be earned by a change: the unpatched
    # repository still builds and keeps its pass_to_pass tests green, so an
    # empty answer would otherwise outscore a wrong patch.
    if "modified_paths" in result.details and not result.details["modified_paths"]:
        failures.append("no_patch_applied")
        components = {key: 0.0 for key in components}

    final_score, normalized_weights = _weighted_score(components, weights)
    stage_score = final_score if normalized_weights else None
    return (
        stage_score,
        {
            "stage_score": _round_optional(stage_score),
            "components": {key: _round(value) for key, value in components.items()},
            "weights": {key: _round(value) for key, value in normalized_weights.items()},
            "counts": counts,
            "success": result.success,
        },
        failures,
    )


def _score_ops(
    scenario: ScenarioSpec,
    result: ExecutorResult,
) -> tuple[float | None, dict[str, Any], list[str]]:
    weights: dict[str, float] = {}
    components: dict[str, float] = {}
    keyword_match_ratios: dict[str, float] = {}
    graded_on: dict[str, str] = {}
    leaked_warnings: dict[str, bool] = {}
    excluded_stages: list[str] = []
    failures: list[str] = []

    rubric = result.details.get("rubric", {})
    if not isinstance(rubric, dict):
        rubric = {}

    stage_specs = (
        ("detection", scenario.success_criteria.require_detection, result.detected),
        ("localization", scenario.success_criteria.require_localization, result.localized),
        ("remediation", scenario.success_criteria.require_repair, result.repaired),
    )

    for stage, required, fallback_flag in stage_specs:
        if not required:
            continue
        report = rubric.get(stage)
        if isinstance(report, dict) and "recall" in report:
            graded_on[stage] = str(report.get("graded_on", ""))
            leaked_warnings[stage] = bool(report.get("all_keywords_leaked", False))
            # An all-keywords-leaked stage carries no discriminative signal; it is
            # excluded from the weighted score entirely (not credited, not
            # penalized) rather than letting a prompt-echo answer score on it.
            if report.get("gradeable") is False:
                excluded_stages.append(stage)
                continue
            # Authoritative leakage-aware recall. The agent's self-reported
            # boolean is intentionally not consulted here.
            score = float(report.get("recall", 0.0))
            passed = bool(report.get("passed", score >= 0.5))
        else:
            # Legacy / synthetic fallback: no rubric available on this result.
            score = 1.0 if fallback_flag else 0.0
            passed = bool(fallback_flag)
            graded_on[stage] = "legacy"
        weights[stage] = OPS_COMPONENT_WEIGHTS[stage]
        components[stage] = score
        keyword_match_ratios[stage] = score
        if not passed:
            failures.append(f"{stage}_incomplete")

    final_score, normalized_weights = _weighted_score(components, weights)
    # No gradeable stage left (none required, or all excluded): the ops stage
    # is not scored at all rather than scored 0.0.
    stage_score = final_score if normalized_weights else None
    breakdown = {
        "stage_score": _round_optional(stage_score),
        "components": {key: _round(value) for key, value in components.items()},
        "weights": {key: _round(value) for key, value in normalized_weights.items()},
        "keyword_recall": {key: _round(value) for key, value in keyword_match_ratios.items()},
        "graded_on": graded_on,
        "success": result.success,
    }
    if any(leaked_warnings.values()):
        breakdown["all_keywords_leaked_stages"] = [
            stage for stage, leaked in leaked_warnings.items() if leaked
        ]
    if excluded_stages:
        # Stages excluded from the score because they were not gradeable
        # (all expected keywords were leaked into the prompt). Authors should add
        # at least one discriminative keyword to make these gradeable.
        breakdown["excluded_stages"] = excluded_stages
    return stage_score, breakdown, failures


def _score_overall(stage_scores: dict[str, float]) -> tuple[float, dict[str, Any]]:
    if not stage_scores:
        return 0.0, {
            "stage_score": None,
            "components": {},
            "weights": {},
        }
    if len(stage_scores) == 1:
        stage_name, stage_score = next(iter(stage_scores.items()))
        return stage_score, {
            "stage_score": _round(stage_score),
            "components": {stage_name: _round(stage_score)},
            "weights": {stage_name: 1.0},
        }

    weights = {
        stage_name: COMBINED_STAGE_WEIGHTS.get(stage_name, 0.0)
        for stage_name in stage_scores
    }
    final_score, normalized_weights = _weighted_score(stage_scores, weights)
    return final_score, {
        "stage_score": _round(final_score),
        "components": {key: _round(value) for key, value in stage_scores.items()},
        "weights": {key: _round(value) for key, value in normalized_weights.items()},
    }


def _weighted_score(
    components: dict[str, float],
    weights: dict[str, float],
) -> tuple[float, dict[str, float]]:
    if not components or not weights:
        return 0.0, {}
    total_weight = sum(weight for key, weight in weights.items() if key in components)
    if total_weight <= 0:
        return 0.0, {}
    normalized_weights = {
        key: weight / total_weight
        for key, weight in weights.items()
        if key in components
    }
    final_score = sum(components[key] * normalized_weights[key] for key in normalized_weights)
    return final_score, normalized_weights


def _ratio(success_count: int, expected_count: int) -> float:
    if expected_count <= 0:
        return 1.0
    return min(success_count, expected_count) / expected_count


def _round(value: float) -> float:
    return round(float(value), 6)


def _round_optional(value: float | None) -> float | None:
    return None if value is None else _round(value)


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
