"""Regression tests: stages with nothing gradeable are excluded, not scored 0.0."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acbench.evaluation.evaluate import (
    _build_group_summary,
    _build_score_summary,
    evaluate_predictions,
)
from acbench.models.result import BenchmarkResult, ExecutorResult
from acbench.models.scenario import ScenarioSpec
from acbench.orchestrator.runner import ACBenchRunner
from acbench.scoring import build_scorecard

REPO_ROOT = Path(__file__).resolve().parents[1]

_ALL_LEAKED_RUBRIC = {
    stage: {
        "recall": 1.0,
        "passed": False,
        "gradeable": False,
        "graded_on": "all_keywords_leaked",
        "all_keywords_leaked": True,
    }
    for stage in ("detection", "localization", "remediation")
}


def _scenario(mode: str, success_criteria: dict) -> ScenarioSpec:
    payload = {
        "scenario_id": f"{mode}-x",
        "title": "x",
        "mode": mode,
        "service": {"application": "a", "service": "s", "repository_path": "repo"},
        "success_criteria": success_criteria,
    }
    if mode in {"ops_only", "combined"}:
        payload["ops_fault"] = {"source": "acbench", "problem_id": "p1"}
    if mode in {"code_only", "combined"}:
        payload["code_fault"] = {"source": "acbench", "defect_id": "d1"}
        payload["build"] = {"test_cmds": ["pytest"]}
    return ScenarioSpec.from_dict(payload)


def _passing_code_result() -> ExecutorResult:
    return ExecutorResult(backend="code", success=True, build_success=True, test_success=True)


class ScorecardExclusionTests(unittest.TestCase):
    def test_ops_stage_with_every_stage_excluded_is_not_gradeable(self) -> None:
        scenario = _scenario(
            "ops_only",
            {"require_detection": True, "require_localization": True, "require_repair": True},
        )
        result = BenchmarkResult(scenario_id="x", title="x", mode="ops_only")
        result.ops_result = ExecutorResult(
            backend="ops", success=True, details={"rubric": _ALL_LEAKED_RUBRIC}
        )

        card = build_scorecard(scenario, result)

        self.assertFalse(card["gradeable"])
        self.assertIsNone(card["final_score"])
        self.assertIsNone(card["ops_score"])
        self.assertEqual(card["code_score"], 0.0)
        self.assertEqual(
            card["score_breakdown"]["ops"]["excluded_stages"],
            ["detection", "localization", "remediation"],
        )

    def test_combined_without_required_ops_stages_scores_code_only(self) -> None:
        # Shape of the perf scenarios: combined, only require_test_success.
        scenario = _scenario("combined", {"require_test_success": True})
        result = BenchmarkResult(scenario_id="x", title="x", mode="combined")
        result.ops_result = ExecutorResult(backend="ops", success=True)
        result.code_result = _passing_code_result()

        card = build_scorecard(scenario, result)

        self.assertTrue(card["gradeable"])
        self.assertEqual(card["final_score"], 1.0)
        self.assertEqual(card["code_score"], 1.0)
        self.assertIsNone(card["ops_score"])
        self.assertEqual(card["score_breakdown"]["overall"]["weights"], {"code": 1.0})

    def test_combined_with_all_ops_stages_excluded_scores_code_only(self) -> None:
        scenario = _scenario(
            "combined",
            {"require_detection": True, "require_repair": True, "require_test_success": True},
        )
        result = BenchmarkResult(scenario_id="x", title="x", mode="combined")
        result.ops_result = ExecutorResult(
            backend="ops", success=True, details={"rubric": _ALL_LEAKED_RUBRIC}
        )
        result.code_result = _passing_code_result()

        card = build_scorecard(scenario, result)

        self.assertEqual(card["final_score"], 1.0)
        self.assertIsNone(card["ops_score"])

    def test_stage_that_did_not_run_still_reports_zero(self) -> None:
        scenario = _scenario("code_only", {"require_test_success": True})
        result = BenchmarkResult(scenario_id="x", title="x", mode="code_only")
        result.code_result = _passing_code_result()

        card = build_scorecard(scenario, result)

        self.assertTrue(card["gradeable"])
        self.assertEqual(card["final_score"], 1.0)
        self.assertEqual(card["ops_score"], 0.0)


class NoPatchCreditTests(unittest.TestCase):
    """An unpatched repo still builds and keeps pass_to_pass green; that earns nothing."""

    def _card(self, modified_paths: list[str]) -> dict:
        scenario = ScenarioSpec.from_dict(
            {
                "scenario_id": "code-x",
                "title": "x",
                "mode": "code_only",
                "service": {"application": "a", "service": "s", "repository_path": "repo"},
                "code_fault": {"source": "acbench", "defect_id": "d1"},
                "build": {"rebuild_cmds": ["build"], "test_cmds": ["pytest"]},
                "evaluation": {"fail_to_pass": ["t.fixed"], "pass_to_pass": ["t.kept"]},
                "success_criteria": {"require_test_success": True},
            }
        )
        result = BenchmarkResult(scenario_id="code-x", title="x", mode="code_only")
        result.code_result = ExecutorResult(
            backend="code",
            success=False,
            build_success=True,
            test_success=False,
            fail_to_pass_failure=["t.fixed"],
            pass_to_pass_success=["t.kept"],
            details={"apply_success": True, "modified_paths": modified_paths},
        )
        return build_scorecard(scenario, result)

    def test_no_patch_earns_no_build_or_pass_to_pass_credit(self) -> None:
        card = self._card([])

        self.assertEqual(card["code_score"], 0.0)
        self.assertIn("code:no_patch_applied", card["failure_reasons"])

    def test_a_patch_that_fixes_nothing_keeps_its_partial_credit(self) -> None:
        card = self._card(["src/app.py"])

        self.assertEqual(card["code_score"], 0.4)
        self.assertNotIn("code:no_patch_applied", card["failure_reasons"])


class SummaryAverageTests(unittest.TestCase):
    def test_stage_averages_keep_zeros_and_skip_stages_that_did_not_run(self) -> None:
        items = {
            "code-pass": {"final_score": 1.0, "code_score": 1.0, "ops_score": 0.0,
                          "code_backend": "code", "ops_backend": ""},
            "code-fail": {"final_score": 0.0, "code_score": 0.0, "ops_score": 0.0,
                          "code_backend": "code", "ops_backend": ""},
            "ops-half": {"final_score": 0.5, "code_score": 0.0, "ops_score": 0.5,
                         "code_backend": "", "ops_backend": "ops"},
        }

        summary = _build_score_summary(items)

        self.assertEqual(summary["average_code_score"], 0.5)
        self.assertEqual(summary["average_ops_score"], 0.5)
        self.assertEqual(summary["average_final_score"], 0.5)
        self.assertEqual(summary["non_gradeable_count"], 0)

    def test_non_gradeable_scenarios_are_skipped_by_averages(self) -> None:
        items = {
            "graded": {"scenario_id": "graded", "mode": "ops_only", "status": "failed",
                       "final_score": 0.4, "ops_score": 0.4, "code_score": 0.0,
                       "ops_backend": "ops", "code_backend": ""},
            "ungraded": {"scenario_id": "ungraded", "mode": "ops_only", "status": "success",
                         "final_score": None, "ops_score": None, "code_score": 0.0,
                         "ops_backend": "ops", "code_backend": ""},
        }

        summary = _build_score_summary(items)
        by_mode = _build_group_summary(items, "mode")["ops_only"]

        self.assertEqual(summary["average_final_score"], 0.4)
        self.assertEqual(summary["average_ops_score"], 0.4)
        self.assertIsNone(summary["average_code_score"])
        self.assertEqual(summary["non_gradeable_count"], 1)
        self.assertEqual(by_mode["average_final_score"], 0.4)
        self.assertEqual(by_mode["submitted"], 2)
        self.assertEqual(by_mode["success_rate"], 0.5)

    def test_all_leaked_scenario_is_non_gradeable_end_to_end(self) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix="acbench-scoring-"))
        self.addCleanup(shutil.rmtree, temp_dir, ignore_errors=True)
        scenario_rel = "tasks/scenarios/local/ops/notifier__dead_letter_queue_overflow.scenario.json"
        manifest = temp_dir / "manifest.json"
        manifest.write_text(json.dumps({"scenarios": [{"scenario": scenario_rel}]}), encoding="utf-8")
        predictions = temp_dir / "predictions.json"
        predictions.write_text(
            json.dumps({
                "_defaults": {"aiops_agent_ref": "acbench.agents.gold_ops:GoldOpsAgent"},
                "ops_only_notifier_dead_letter_queue_overflow": {},
            }),
            encoding="utf-8",
        )

        with patch(
            "acbench.evaluation.evaluate.ACBenchRunner",
            lambda: ACBenchRunner(root_dir=temp_dir),
        ):
            results = evaluate_predictions(manifest, predictions, temp_dir / "eval.json")

        item = results["results"]["ops_only_notifier_dead_letter_queue_overflow"]
        self.assertFalse(item["gradeable"])
        self.assertIsNone(item["final_score"])
        self.assertIsNone(results["score_summary"]["average_final_score"])
        self.assertEqual(results["score_summary"]["non_gradeable_count"], 1)
        # The per-run summary.json carries the same non-score.
        summary = json.loads(Path(item["summary_path"]).read_text(encoding="utf-8"))
        self.assertIsNone(summary["final_score"])


if __name__ == "__main__":
    unittest.main()
