"""Tests for the inspect-ai adapter (skipped if inspect-ai is not installed)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from inspect_ai import eval as inspect_eval
    from inspect_ai.model import ModelOutput, get_model
    HAVE_INSPECT = True
except Exception:  # pragma: no cover - exercised when inspect-ai is absent
    HAVE_INSPECT = False

from acbench.models.scenario import ScenarioSpec

REPO = Path(__file__).resolve().parents[1]


def _manifest(scenario_rel: str) -> str:
    payload = {"name": "t", "scenarios": [{"scenario": scenario_rel}]}
    path = Path(tempfile.mkdtemp(prefix="acbench-inspect-")) / "m.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _gold_assessment(scenario: ScenarioSpec) -> str:
    fault = scenario.ops_fault
    return json.dumps({
        "detected": True, "localized": True, "repaired": True,
        "summary": "incident " + ", ".join(fault.detection_keywords),
        "root_cause": "root cause " + ", ".join(fault.localization_keywords),
        "remediation": "fix " + ", ".join(fault.repair_keywords),
        "evidence": list(fault.detection_keywords),
    })


@unittest.skipUnless(HAVE_INSPECT, "inspect-ai not installed")
class InspectAdapterTests(unittest.TestCase):
    def _run(self, manifest: str, outputs: list[str]):
        from acbench.integrations.inspect_ai import acbench_task

        model = get_model(
            "mockllm/model",
            custom_outputs=[ModelOutput.from_content("mockllm/model", o) for o in outputs],
        )
        logs = inspect_eval(acbench_task(manifest=manifest), model=model, display="none")
        return logs[0]

    def test_code_only_gold_patch_scores_full(self) -> None:
        manifest = _manifest(
            "tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json"
        )
        gold = (REPO / "patches" / "billing_pricing_bundle_fix.diff").read_text(encoding="utf-8")
        log = self._run(manifest, [gold])
        score = log.samples[0].scores["acbench_scorer"]
        self.assertEqual(log.status, "success")
        self.assertEqual(score.value, 1.0)
        self.assertEqual(score.metadata["code_score"], 1.0)

    def test_ops_only_gold_assessment_scores(self) -> None:
        rel = "tasks/scenarios/local/ops/api_server__db_connection_pool_exhaustion.scenario.json"
        scenario = ScenarioSpec.from_file(REPO / rel)
        log = self._run(_manifest(rel), [_gold_assessment(scenario)])
        score = log.samples[0].scores["acbench_scorer"]
        self.assertEqual(log.status, "success")
        self.assertGreater(score.metadata["ops_score"], 0.5)

    def test_combined_two_step(self) -> None:
        rel = "tasks/scenarios/local/combined/billing_pricing__checkout_totals_incident.scenario.json"
        scenario = ScenarioSpec.from_file(REPO / rel)
        gold = (REPO / "patches" / "billing_pricing_bundle_fix.diff").read_text(encoding="utf-8")
        # Combined makes two generate calls: diagnosis, then patch.
        log = self._run(_manifest(rel), [_gold_assessment(scenario), gold])
        score = log.samples[0].scores["acbench_scorer"]
        self.assertEqual(log.status, "success")
        self.assertEqual(score.metadata["code_score"], 1.0)
        self.assertGreater(score.value, 0.5)


if __name__ == "__main__":
    unittest.main()
