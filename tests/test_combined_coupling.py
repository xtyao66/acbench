"""Tests for end-to-end coupling of ops diagnosis into the code stage."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from acbench.agents.coupling import format_ops_diagnosis, localization_consistent
from acbench.agents.openai_code import OpenAICodePatchAgent
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec
from acbench.orchestrator.runner import ACBenchRunner

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_PATCH = REPO_ROOT / "patches" / "billing_pricing_bundle_fix.diff"


class _RecordingCodeAgent:
    """Code agent that records the ops diagnosis it received, then returns gold."""

    captured: object = "unset"

    def generate_patch(self, scenario, run_config, *, output_dir):
        type(self).captured = run_config.upstream_ops_diagnosis
        return {"patch_text": GOLD_PATCH.read_text(encoding="utf-8"), "telemetry": {}}


class CombinedCouplingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="acbench-coupling-"))
        _RecordingCodeAgent.captured = "unset"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_runner_threads_diagnosis_into_code_stage(self) -> None:
        runner = ACBenchRunner(root_dir=self.temp_dir)
        scenario_path = (
            REPO_ROOT / "tasks" / "scenarios" / "local" / "combined"
            / "billing_pricing__checkout_totals_incident.scenario.json"
        )
        result = runner.run(
            scenario_path,
            dry_run=False,
            run_config=RunConfig(
                dry_run=False,
                aiops_agent_ref="acbench.agents.gold_ops:GoldOpsAgent",
                code_agent_ref="tests.test_combined_coupling:_RecordingCodeAgent",
                openai_model="test-model",
                max_steps=5,
            ),
        )

        # The code agent actually received the ops diagnosis.
        self.assertIsInstance(_RecordingCodeAgent.captured, dict)
        self.assertTrue(str(_RecordingCodeAgent.captured.get("root_cause", "")))

        # It is recorded on the code result and surfaced in the scorecard.
        self.assertTrue(result.code_result.details["ops_diagnosis_provided"])
        coupling = result.unified_metrics["score_breakdown"]["coupling"]
        self.assertTrue(coupling["ops_diagnosis_provided"])
        self.assertEqual(result.status, "success")

    def test_disable_coupling_runs_stages_independently(self) -> None:
        runner = ACBenchRunner(root_dir=self.temp_dir)
        scenario_path = (
            REPO_ROOT / "tasks" / "scenarios" / "local" / "combined"
            / "billing_pricing__checkout_totals_incident.scenario.json"
        )
        result = runner.run(
            scenario_path,
            dry_run=False,
            run_config=RunConfig(
                dry_run=False,
                aiops_agent_ref="acbench.agents.gold_ops:GoldOpsAgent",
                code_agent_ref="tests.test_combined_coupling:_RecordingCodeAgent",
                openai_model="test-model",
                max_steps=5,
                disable_coupling=True,
            ),
        )
        # Ablation: the code agent must NOT have received the ops diagnosis.
        self.assertIsNone(_RecordingCodeAgent.captured)
        self.assertFalse(result.code_result.details["ops_diagnosis_provided"])

    def test_code_only_run_has_no_diagnosis(self) -> None:
        runner = ACBenchRunner(root_dir=self.temp_dir)
        scenario_path = (
            REPO_ROOT / "tasks" / "scenarios" / "local" / "code"
            / "billing_pricing__bundle_discount_threshold.scenario.json"
        )
        result = runner.run(
            scenario_path,
            dry_run=False,
            run_config=RunConfig(dry_run=False, code_patch_path=str(GOLD_PATCH)),
        )
        self.assertFalse(result.code_result.details["ops_diagnosis_provided"])
        self.assertNotIn("coupling", result.unified_metrics["score_breakdown"])


class CouplingHelperTests(unittest.TestCase):
    def test_format_ops_diagnosis(self) -> None:
        text = format_ops_diagnosis(
            {"summary": "Totals wrong", "root_cause": "bundle threshold off-by-one",
             "remediation": "fix threshold", "evidence": ["unit test fails"]}
        )
        self.assertIn("UPSTREAM OPS DIAGNOSIS", text)
        self.assertIn("bundle threshold off-by-one", text)
        self.assertEqual(format_ops_diagnosis(None), "")

    def test_localization_consistency_signal(self) -> None:
        self.assertTrue(
            localization_consistent(
                {"root_cause": "x"}, ["src/billing_pricing/pricing.py"], ["pricing"]
            )
        )
        self.assertIsNone(localization_consistent(None, ["a.py"], ["a"]))

    def test_prompt_includes_diagnosis_when_present(self) -> None:
        scenario = ScenarioSpec.from_file(
            REPO_ROOT / "tasks" / "scenarios" / "local" / "code"
            / "billing_pricing__bundle_discount_threshold.scenario.json"
        )
        repo_root = Path(scenario.service.repository_path)
        if not repo_root.is_absolute():
            repo_root = REPO_ROOT / scenario.service.repository_path
        run_config = RunConfig(
            upstream_ops_diagnosis={"root_cause": "off-by-one bundle threshold",
                                    "summary": "s", "remediation": "r"}
        )
        prompt = OpenAICodePatchAgent()._build_repository_prompt(scenario, repo_root, run_config)
        self.assertIn("UPSTREAM OPS DIAGNOSIS", prompt)
        self.assertIn("off-by-one bundle threshold", prompt)

    def test_hide_fault_location_does_not_label_target(self) -> None:
        scenario = ScenarioSpec.from_file(
            REPO_ROOT / "tasks" / "scenarios" / "local" / "code"
            / "billing_pricing__bundle_discount_threshold.scenario.json"
        )
        repo_root = Path(scenario.service.repository_path)
        if not repo_root.is_absolute():
            repo_root = REPO_ROOT / scenario.service.repository_path
        shown = OpenAICodePatchAgent()._build_repository_prompt(scenario, repo_root, RunConfig())
        hidden = OpenAICodePatchAgent()._build_repository_prompt(
            scenario, repo_root, RunConfig(hide_fault_location=True)
        )
        self.assertIn("Target files and nearby test context:", shown)
        self.assertNotIn("Target files and nearby test context:", hidden)
        self.assertIn("the faulty file is NOT identified", hidden)


if __name__ == "__main__":
    unittest.main()
