"""Batch evaluation utilities for the ACBench."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from acbench.agents.profile import apply_agent_profile_to_payload
from acbench.models.runtime import RunConfig
from acbench.orchestrator.runner import ACBenchRunner
from acbench.paths import resolve_repo_path
from acbench.scoring import build_scorecard


def _resolve_patch_input(
    scenario_path: Path,
    payload: dict[str, Any],
) -> str:
    """Resolve a patch file path from a prediction entry.

    Inline ``model_patch`` text is not handled here: the runner writes it into
    the scenario's own run directory (see ``evaluate_predictions``).
    """

    scenario = ACBenchRunner().load_scenario(scenario_path)
    if payload.get("use_gold_patch"):
        if not scenario.gold_patch_path:
            raise ValueError(
                f"Scenario {scenario.scenario_id} does not define gold_patch_path."
            )
        return scenario.gold_patch_path
    if payload.get("code_patch_path"):
        return str(payload["code_patch_path"])
    if payload.get("model_patch_path"):
        return str(payload["model_patch_path"])
    return ""


def _build_run_config(
    payload: dict[str, Any],
    *,
    patch_path: str,
) -> RunConfig:
    """Build one RunConfig from one prediction payload."""

    payload = apply_agent_profile_to_payload(payload)
    return RunConfig(
        dry_run=bool(payload.get("dry_run", False)),
        code_patch_path=patch_path,
        aiops_agent_ref=str(payload.get("aiops_agent_ref", "")),
        code_agent_ref=str(payload.get("code_agent_ref", "")),
        agent_config_path=str(payload.get("agent_config_path", payload.get("agent_config", ""))),
        agent_profile_name=str(payload.get("agent_profile_name", "")),
        code_agent_config=dict(payload.get("code_agent_config", {})),
        ops_agent_config=dict(payload.get("ops_agent_config", {})),
        openai_model=str(payload.get("openai_model", "")),
        openai_api_key_env=str(payload.get("openai_api_key_env", "OPENAI_API_KEY")),
        openai_base_url=str(payload.get("openai_base_url", "")),
        anthropic_model=str(payload.get("anthropic_model", "")),
        anthropic_api_key_env=str(
            payload.get("anthropic_api_key_env", "ANTHROPIC_API_KEY")
        ),
        anthropic_base_url=str(
            payload.get("anthropic_base_url", "https://api.anthropic.com")
        ),
        anthropic_version=str(payload.get("anthropic_version", "2023-06-01")),
        max_steps=int(payload.get("max_steps", 10)),
        keep_artifacts=bool(payload.get("keep_artifacts", True)),
        allow_synthetic_ops=bool(payload.get("allow_synthetic_ops", False)),
        disable_coupling=bool(payload.get("disable_coupling", False)),
    )


def evaluate_predictions(
    manifest_path: str | Path,
    predictions_path: str | Path,
    output_path: str | Path,
    overrides: dict[str, Any] | None = None,
    configure_run: Callable[[RunConfig], None] | None = None,
) -> dict[str, Any]:
    """Evaluate a prediction bundle against a scenario manifest.

    ``overrides`` (e.g. explicit command-line flags) take precedence over both
    the predictions file's ``_defaults`` and each scenario's entry.
    ``configure_run``, when given, adjusts each RunConfig before it runs.
    """

    manifest_file = resolve_repo_path(manifest_path)
    predictions_file = resolve_repo_path(predictions_path)
    output_file = Path(output_path)

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    predictions = json.loads(predictions_file.read_text(encoding="utf-8"))
    prediction_defaults = predictions.get("_defaults", {})
    if prediction_defaults and not isinstance(prediction_defaults, dict):
        raise ValueError("Prediction `_defaults` must be a JSON object when present.")
    runner = ACBenchRunner()

    results: dict[str, Any] = {
        "manifest": str(manifest_file),
        "predictions": str(predictions_file),
        "submitted": 0,
        "success": 0,
        "failure": 0,
        "missing": [],
        "results": {},
        "timing_summary": {},
        "score_summary": {},
        "by_mode": {},
        "by_source": {},
        "by_difficulty": {},
    }

    for entry in manifest["scenarios"]:
        scenario_path = resolve_repo_path(entry["scenario"])
        scenario = runner.load_scenario(scenario_path)
        pred = predictions.get(scenario.scenario_id)
        if pred is None:
            results["missing"].append(scenario.scenario_id)
            continue
        if not isinstance(pred, dict):
            raise ValueError(
                f"Prediction payload for {scenario.scenario_id} must be a JSON object."
            )

        merged_pred = dict(prediction_defaults)
        merged_pred.update(pred)
        merged_pred.update(overrides or {})

        patch_path = _resolve_patch_input(scenario_path, merged_pred)
        # Inline patch text goes into this scenario's own run directory, so
        # concurrent evaluations never read each other's patch file.
        inline_patch = (
            str(merged_pred["model_patch"])
            if not patch_path and merged_pred.get("model_patch")
            else None
        )
        run_config = _build_run_config(
            merged_pred,
            patch_path=patch_path,
        )
        if configure_run is not None:
            configure_run(run_config)
        run_result = runner.run(
            scenario_path=scenario_path,
            dry_run=run_config.dry_run,
            run_config=run_config,
            inline_patch=inline_patch,
        )
        scorecard = build_scorecard(scenario, run_result)
        code_result = run_result.code_result
        ops_result = run_result.ops_result
        summary = {
            "scenario_id": scenario.scenario_id,
            "title": scenario.title,
            "mode": scenario.mode,
            "source_type": scenario.source.type,
            "difficulty": scenario.metadata.difficulty or "unknown",
            "application": scenario.service.application,
            "service": scenario.service.service,
            "status": run_result.status,
            "result_path": run_result.artifacts.result_path,
            "summary_path": run_result.artifacts.summary_path,
            "code_backend": code_result.backend if code_result else "",
            "ops_backend": ops_result.backend if ops_result else "",
            "run_total_seconds": run_result.unified_metrics.get("run_total_seconds", 0.0),
            "final_score": scorecard["final_score"],
            "ops_score": scorecard["ops_score"],
            "code_score": scorecard["code_score"],
            "gradeable": scorecard["gradeable"],
            "score_breakdown": scorecard["score_breakdown"],
            "failure_reasons": scorecard["failure_reasons"],
            "build_success": code_result.build_success if code_result else False,
            "test_success": code_result.test_success if code_result else False,
            "detected": ops_result.detected if ops_result else False,
            "localized": ops_result.localized if ops_result else False,
            "repaired": (
                code_result.repaired
                if code_result
                else (ops_result.repaired if ops_result else False)
            ),
            "pass_to_pass_success": code_result.pass_to_pass_success if code_result else [],
            "fail_to_pass_success": code_result.fail_to_pass_success if code_result else [],
            "pass_to_pass_failure": code_result.pass_to_pass_failure if code_result else [],
            "fail_to_pass_failure": code_result.fail_to_pass_failure if code_result else [],
            "code_executor_total_seconds": code_result.metrics.get(
                "executor_total_seconds",
                0.0,
            ) if code_result else 0.0,
            "ops_executor_total_seconds": ops_result.metrics.get(
                "executor_total_seconds",
                0.0,
            ) if ops_result else 0.0,
            "code_agent_answer_count": code_result.metrics.get(
                "agent_answer_count",
                0,
            ) if code_result else 0,
            "ops_agent_answer_count": ops_result.metrics.get(
                "agent_answer_count",
                0,
            ) if ops_result else 0,
            "code_agent_answer_durations_seconds": code_result.metrics.get(
                "agent_answer_durations_seconds",
                [],
            ) if code_result else [],
            "ops_agent_answer_durations_seconds": ops_result.metrics.get(
                "agent_answer_durations_seconds",
                [],
            ) if ops_result else [],
            "code_agent_total_answer_seconds": code_result.metrics.get(
                "agent_total_answer_seconds",
                0.0,
            ) if code_result else 0.0,
            "ops_agent_total_answer_seconds": ops_result.metrics.get(
                "agent_total_answer_seconds",
                0.0,
            ) if ops_result else 0.0,
            "code_agent_average_answer_seconds": code_result.metrics.get(
                "agent_average_answer_seconds",
                0.0,
            ) if code_result else 0.0,
            "ops_agent_average_answer_seconds": ops_result.metrics.get(
                "agent_average_answer_seconds",
                0.0,
            ) if ops_result else 0.0,
        }
        results["results"][scenario.scenario_id] = summary
        results["submitted"] += 1
        if run_result.status == "success":
            results["success"] += 1
        else:
            results["failure"] += 1

    submitted = int(results["submitted"])
    run_total_seconds = sum(
        float(item.get("run_total_seconds", 0.0))
        for item in results["results"].values()
    )
    code_answer_count = sum(
        int(item.get("code_agent_answer_count", 0))
        for item in results["results"].values()
    )
    ops_answer_count = sum(
        int(item.get("ops_agent_answer_count", 0))
        for item in results["results"].values()
    )
    code_total_answer_seconds = sum(
        float(item.get("code_agent_total_answer_seconds", 0.0))
        for item in results["results"].values()
    )
    ops_total_answer_seconds = sum(
        float(item.get("ops_agent_total_answer_seconds", 0.0))
        for item in results["results"].values()
    )
    total_answer_count = code_answer_count + ops_answer_count
    total_answer_seconds = code_total_answer_seconds + ops_total_answer_seconds
    results["timing_summary"] = {
        "scenario_run_total_seconds": round(run_total_seconds, 6),
        "scenario_run_average_seconds": round(
            run_total_seconds / submitted,
            6,
        ) if submitted else 0.0,
        "code_agent_answer_count": code_answer_count,
        "ops_agent_answer_count": ops_answer_count,
        "total_agent_answer_count": total_answer_count,
        "code_agent_total_answer_seconds": round(code_total_answer_seconds, 6),
        "ops_agent_total_answer_seconds": round(ops_total_answer_seconds, 6),
        "total_agent_answer_seconds": round(total_answer_seconds, 6),
        "overall_agent_average_answer_seconds": round(
            total_answer_seconds / total_answer_count,
            6,
        ) if total_answer_count else 0.0,
    }
    results["score_summary"] = _build_score_summary(results["results"])
    results["by_mode"] = _build_group_summary(results["results"], "mode")
    results["by_source"] = _build_group_summary(results["results"], "source_type")
    results["by_difficulty"] = _build_group_summary(results["results"], "difficulty")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def _mean_or_none(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _build_score_summary(result_items: dict[str, Any]) -> dict[str, Any]:
    # Each average runs over the scenarios it applies to, keeping genuine 0.0
    # scores: final over gradeable scenarios, code/ops over scenarios that ran
    # that stage and got a score. No applicable scenario -> None.
    items = list(result_items.values())
    final_scores = [
        float(item["final_score"]) for item in items if item.get("final_score") is not None
    ]
    code_scores = [
        float(item["code_score"])
        for item in items
        if item.get("code_backend") and item.get("code_score") is not None
    ]
    ops_scores = [
        float(item["ops_score"])
        for item in items
        if item.get("ops_backend") and item.get("ops_score") is not None
    ]

    return {
        "average_final_score": _mean_or_none(final_scores),
        "average_code_score": _mean_or_none(code_scores),
        "average_ops_score": _mean_or_none(ops_scores),
        "non_gradeable_count": len(items) - len(final_scores),
    }


def _build_group_summary(
    result_items: dict[str, Any],
    field_name: str,
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}

    for item in result_items.values():
        group_key = str(item.get(field_name, "unknown") or "unknown")
        group = grouped.setdefault(
            group_key,
            {
                "submitted": 0,
                "success": 0,
                "failure": 0,
                "total_final_score": 0.0,
                "scored": 0,
                "scenario_ids": [],
            },
        )
        group["submitted"] += 1
        if item.get("status") == "success":
            group["success"] += 1
        else:
            group["failure"] += 1
        # Non-gradeable scenarios (final_score None) are left out of the average.
        if item.get("final_score") is not None:
            group["total_final_score"] += float(item["final_score"])
            group["scored"] += 1
        group["scenario_ids"].append(str(item.get("scenario_id", "")))

    for group in grouped.values():
        submitted = int(group["submitted"])
        scored = int(group["scored"])
        group["success_rate"] = round(group["success"] / submitted, 6) if submitted else 0.0
        group["average_final_score"] = round(
            group["total_final_score"] / scored,
            6,
        ) if scored else None
        del group["total_final_score"]
        del group["scored"]

    return grouped
