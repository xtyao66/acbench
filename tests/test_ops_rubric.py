"""Tests for the leakage-aware, self-report-free ops grading rubric."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acbench.executors.backends.ops.rubric import (
    evaluate_stage,
    prompt_text_for_problem,
)
from acbench.executors.backends.ops.engine import AgentDrivenOpsEngine
from acbench.executors.backends.ops.runtime import NativeOpsProblem, OpsRunRequest


class _EchoOpsAgent:
    """Ops agent that only parrots the visible incident prompt back."""

    def configure(self, **kwargs) -> None:  # pragma: no cover - trivial
        self.config = kwargs

    def analyze(self, problem, *, output_dir: Path) -> dict[str, object]:
        output_dir.mkdir(parents=True, exist_ok=True)
        echoed = prompt_text_for_problem(problem)
        assessment = {
            # Claims full success, but only echoes the prompt — no real diagnosis.
            "detected": True,
            "localized": True,
            "repaired": True,
            "summary": echoed,
            "root_cause": echoed,
            "remediation": echoed,
            "evidence": list(problem.error_logs or []),
        }
        return {"assessment": assessment, "telemetry": {}}


class OpsRubricTests(unittest.TestCase):
    def test_prompt_echo_earns_no_discriminative_credit(self) -> None:
        # "pool exhausted" is leaked in the prompt; "AsyncSession" is not.
        report = evaluate_stage(
            "localization",
            assessment={"root_cause": "the pool exhausted under load"},
            keywords=["pool exhausted", "AsyncSession"],
            prompt_text="users see 503 because the pool exhausted at peak",
        )
        self.assertEqual(report.leaked, ["pool exhausted"])
        self.assertEqual(report.discriminative, ["AsyncSession"])
        # Only the leaked keyword was produced -> 0 discriminative recall -> fail.
        self.assertEqual(report.recall, 0.0)
        self.assertFalse(report.passed)
        self.assertEqual(report.graded_on, "discriminative")

    def test_discriminative_answer_passes(self) -> None:
        report = evaluate_stage(
            "localization",
            assessment={"root_cause": "the AsyncSession pool is too small"},
            keywords=["pool exhausted", "AsyncSession"],
            prompt_text="users see 503 because the pool exhausted at peak",
        )
        self.assertIn("AsyncSession", report.matched_discriminative)
        self.assertEqual(report.recall, 1.0)
        self.assertTrue(report.passed)

    def test_self_report_is_ignored(self) -> None:
        # Empty assessment but stage keyword absent -> must fail regardless of any
        # self-reported flag (the rubric never reads 'detected'/'localized').
        report = evaluate_stage(
            "detection",
            assessment={"detected": True, "summary": "everything looks fine"},
            keywords=["disk pressure"],
            prompt_text="latency rose sharply",
        )
        self.assertFalse(report.passed)

    def test_all_keywords_leaked_is_not_gradeable(self) -> None:
        report = evaluate_stage(
            "detection",
            assessment={"summary": "the timeout fired"},
            keywords=["timeout"],
            prompt_text="the request hit a timeout and failed",
        )
        # No discriminative signal possible: the stage is flagged AND not gradeable
        # (echoing the prompt no longer earns credit).
        self.assertEqual(report.discriminative, [])
        self.assertTrue(report.all_keywords_leaked)
        self.assertEqual(report.graded_on, "all_keywords_leaked")
        self.assertFalse(report.gradeable)
        self.assertFalse(report.passed)

    def test_all_leaked_stage_is_excluded_from_ops_score(self) -> None:
        from acbench.models.result import BenchmarkResult, ExecutorResult
        from acbench.models.scenario import ScenarioSpec
        from acbench.scoring import build_scorecard

        scenario = ScenarioSpec.from_dict({
            "scenario_id": "ops-excl", "title": "x", "mode": "ops_only",
            "service": {"application": "a", "service": "s"},
            "ops_fault": {"source": "acbench", "problem_id": "p1"},
            "success_criteria": {"require_detection": True,
                                 "require_localization": True, "require_repair": True},
        })
        result = BenchmarkResult(scenario_id="ops-excl", title="x", mode="ops_only")
        result.ops_result = ExecutorResult(
            backend="acbench-local-ops", success=True,
            detected=True, localized=True, repaired=True,
            details={"rubric": {
                "detection": {"recall": 1.0, "passed": False, "gradeable": False,
                              "graded_on": "all_keywords_leaked", "all_keywords_leaked": True},
                "localization": {"recall": 1.0, "passed": True, "gradeable": True,
                                 "graded_on": "discriminative", "all_keywords_leaked": False},
                "remediation": {"recall": 1.0, "passed": True, "gradeable": True,
                                "graded_on": "discriminative", "all_keywords_leaked": False},
            }},
        )
        card = build_scorecard(scenario, result)
        ops_bd = card["score_breakdown"]["ops"]
        # Detection (all-leaked) is excluded; score reflects only the gradeable stages.
        self.assertIn("detection", ops_bd.get("excluded_stages", []))
        self.assertNotIn("detection", ops_bd["components"])
        self.assertEqual(card["ops_score"], 1.0)

    def test_threshold_requires_majority_of_discriminative_keywords(self) -> None:
        report = evaluate_stage(
            "remediation",
            assessment={"remediation": "increase pool_size"},
            keywords=["pool_size", "max_overflow", "pool_timeout"],
            prompt_text="incident: connections exhausted",
        )
        # 1 of 3 discriminative keywords -> recall 0.33 < 0.5 -> fail.
        self.assertAlmostEqual(report.recall, 1 / 3, places=3)
        self.assertFalse(report.passed)

    def test_engine_rejects_prompt_echoing_agent(self) -> None:
        engine = AgentDrivenOpsEngine()
        problem = NativeOpsProblem(
            problem_id="p-echo",
            source="acbench",
            application="api",
            service="api-server",
            issue_text="users see 503 errors",
            error_logs=["connection pool exhausted"],
            require_detection=True,
            require_localization=True,
            require_repair=True,
            detection_keywords=["503"],
            localization_keywords=["AsyncSession pool"],
            repair_keywords=["increase pool_size"],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            outcome = engine.run(
                OpsRunRequest(
                    problem=problem,
                    output_dir=Path(tmp_dir),
                    agent_ref="tests.test_ops_rubric:_EchoOpsAgent",
                )
            )
        # Localization/remediation keywords are NOT in the prompt, so echoing fails them.
        self.assertFalse(outcome.localized)
        self.assertFalse(outcome.repaired)
        self.assertFalse(outcome.success)
        # And the model's self-reported booleans are recorded but not graded.
        self.assertTrue(outcome.metrics["self_reported_localized"])


if __name__ == "__main__":
    unittest.main()
