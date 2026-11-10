"""Tests for batch prediction evaluation."""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from acbench.evaluation.evaluate import evaluate_predictions
from acbench.orchestrator import cli
from acbench.orchestrator.runner import ACBenchRunner
from acbench.paths import repo_root
from scripts.run_agent_evals import build_parser, default_output


class EvaluateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="acbench-eval-"))
        self.output_path = self.temp_dir / "results.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_local_gold_manifest_evaluation(self) -> None:
        results = evaluate_predictions(
            manifest_path=Path("manifests/local_suite.json"),
            predictions_path=Path("predictions/local_gold.json"),
            output_path=self.output_path,
        )

        self.assertEqual(results["submitted"], 12)
        # Every required stage of the notifier DLQ scenario has all its keywords
        # leaked into the prompt, so it is not gradeable and even gold cannot succeed.
        self.assertEqual(results["success"], 11)
        self.assertEqual(results["score_summary"]["non_gradeable_count"], 1)
        self.assertTrue(self.output_path.exists())
        payload = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertFalse(
            payload["results"]["ops_only_notifier_dead_letter_queue_overflow"]["gradeable"]
        )
        self.assertIn("code_only_billing_pricing_bundle_threshold", payload["results"])
        self.assertIn("ops_only_cache_api_stale_index", payload["results"])
        self.assertIn("combined_billing_pricing_checkout_totals", payload["results"])
        self.assertIn("score_summary", payload)
        self.assertIn("by_mode", payload)
        self.assertIn("by_source", payload)
        self.assertIn("by_difficulty", payload)
        self.assertIn("final_score", payload["results"]["code_only_billing_pricing_bundle_threshold"])
        self.assertIn(
            "score_breakdown",
            payload["results"]["ops_only_cache_api_stale_index"],
        )
        self.assertIn(
            "failure_reasons",
            payload["results"]["combined_billing_pricing_checkout_totals"],
        )
        self.assertIn("code_only", payload["by_mode"])
        self.assertIn("local_fixture", payload["by_source"])

    def test_prediction_defaults_can_drive_agent_runs(self) -> None:
        manifest_path = self.temp_dir / "single_scenario_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "name": "single-code-scenario",
                    "scenarios": [
                        {
                            "scenario": "tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json"
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        predictions_path = self.temp_dir / "agent_predictions.json"
        predictions_path.write_text(
            json.dumps(
                {
                    "_defaults": {
                        "code_agent_ref": "tests.test_standalone_code_executor:FakePatchAgent",
                        "openai_model": "test-model",
                    },
                    "code_only_billing_pricing_bundle_threshold": {},
                }
            ),
            encoding="utf-8",
        )

        results = evaluate_predictions(
            manifest_path=manifest_path,
            predictions_path=predictions_path,
            output_path=self.output_path,
        )

        self.assertEqual(results["submitted"], 1)
        self.assertEqual(results["success"], 1)
        self.assertIn(
            "code_only_billing_pricing_bundle_threshold",
            results["results"],
        )
        scenario_result = results["results"]["code_only_billing_pricing_bundle_threshold"]
        self.assertIn("final_score", scenario_result)
        self.assertGreater(scenario_result["final_score"], 0.0)

    def test_prediction_defaults_can_drive_ops_agent_runs(self) -> None:
        manifest_path = self.temp_dir / "single_ops_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "name": "single-ops-scenario",
                    "scenarios": [
                        {
                            "scenario": "tasks/scenarios/local/ops/queue_worker__backlog_spike.scenario.json"
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        predictions_path = self.temp_dir / "agent_ops_predictions.json"
        predictions_path.write_text(
            json.dumps(
                {
                    "_defaults": {
                        "aiops_agent_ref": "tests.test_openai_ops_agent:FakeOpsAssessmentAgent",
                        "openai_model": "test-model",
                    },
                    "ops_only_queue_worker_backlog_spike": {},
                }
            ),
            encoding="utf-8",
        )

        results = evaluate_predictions(
            manifest_path=manifest_path,
            predictions_path=predictions_path,
            output_path=self.output_path,
        )

        self.assertEqual(results["submitted"], 1)
        self.assertEqual(results["success"], 1)
        self.assertEqual(
            results["results"]["ops_only_queue_worker_backlog_spike"]["ops_backend"],
            "acbench-local-ops",
        )
        self.assertIn(
            "ops",
            results["results"]["ops_only_queue_worker_backlog_spike"]["score_breakdown"],
        )


COMBINED_SCENARIO = "tasks/scenarios/local/combined/billing_pricing__checkout_totals_incident.scenario.json"
COMBINED_ID = "combined_billing_pricing_checkout_totals"
CODE_SCENARIO = "tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json"
CODE_ID = "code_only_billing_pricing_bundle_threshold"
GOLD_OPS = "acbench.agents.gold_ops:GoldOpsAgent"


class BatchRunInputTests(unittest.TestCase):
    """Batch runs honour CLI flags and keep inline patches inside the run directory."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="acbench-batch-"))
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        runner_patch = patch(
            "acbench.evaluation.evaluate.ACBenchRunner",
            lambda: ACBenchRunner(root_dir=self.temp_dir),
        )
        runner_patch.start()
        self.addCleanup(runner_patch.stop)

    def _write_inputs(self, scenario_rel: str, predictions: dict) -> tuple[Path, Path]:
        manifest = self.temp_dir / "manifest.json"
        manifest.write_text(json.dumps({"scenarios": [{"scenario": scenario_rel}]}), encoding="utf-8")
        predictions_path = self.temp_dir / "predictions.json"
        predictions_path.write_text(json.dumps(predictions), encoding="utf-8")
        return manifest, predictions_path

    def _run_cli(self, *argv: str) -> dict:
        output = self.temp_dir / "eval.json"
        with patch.object(sys, "argv", ["acbench", *argv, "--evaluation-output", str(output)]):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(), 0)
        return json.loads(output.read_text(encoding="utf-8"))

    @staticmethod
    def _run_config(item: dict) -> dict:
        diagnostics = Path(item["result_path"]).parent / "diagnostics.json"
        return json.loads(diagnostics.read_text(encoding="utf-8"))["run_config"]

    def test_cli_run_flags_override_predictions_file_in_batch_mode(self) -> None:
        manifest, predictions = self._write_inputs(
            COMBINED_SCENARIO,
            {
                "_defaults": {"max_steps": 3, "disable_coupling": False},
                COMBINED_ID: {"dry_run": False},
            },
        )

        results = self._run_cli(
            "--manifest", str(manifest), "--predictions", str(predictions),
            "--dry-run", "--disable-coupling", "--allow-synthetic-ops",
            "--aiops-agent-ref", GOLD_OPS, "--max-steps", "7",
        )

        item = results["results"][COMBINED_ID]
        self.assertEqual(item["ops_backend"], "dry-run-ops")
        run_config = self._run_config(item)
        self.assertTrue(run_config["dry_run"])
        self.assertTrue(run_config["disable_coupling"])
        self.assertTrue(run_config["allow_synthetic_ops"])
        self.assertEqual(run_config["aiops_agent_ref"], GOLD_OPS)
        self.assertEqual(run_config["max_steps"], 7)

    def test_cli_agent_config_and_model_flag_apply_in_batch_mode(self) -> None:
        profile = self.temp_dir / "profile.json"
        profile.write_text(
            json.dumps({"name": "batch-profile", "code": {"provider": "openai", "model": "profile-model"}}),
            encoding="utf-8",
        )
        manifest, predictions = self._write_inputs(
            CODE_SCENARIO, {"_defaults": {"aiops_agent_ref": GOLD_OPS}, CODE_ID: {}}
        )

        results = self._run_cli(
            "--manifest", str(manifest), "--predictions", str(predictions),
            "--dry-run", "--agent-config", str(profile), "--openai-model", "cli-model",
        )

        run_config = self._run_config(results["results"][CODE_ID])
        self.assertEqual(run_config["agent_profile_name"], "batch-profile")
        self.assertEqual(run_config["code_agent_ref"], "acbench.agents.openai_code:OpenAICodePatchAgent")
        # The profile defines both agents, as in single-scenario runs.
        self.assertEqual(run_config["aiops_agent_ref"], "")
        self.assertEqual(run_config["code_agent_model"], "cli-model")

    def test_cli_rejects_single_scenario_flags_in_batch_mode(self) -> None:
        manifest, predictions = self._write_inputs(CODE_SCENARIO, {CODE_ID: {}})
        for extra in (["--scenario", CODE_SCENARIO], ["--code-patch", "patches/x.diff"]):
            argv = ["acbench", "--manifest", str(manifest), "--predictions", str(predictions),
                    "--evaluation-output", str(self.temp_dir / "eval.json"), *extra]
            with patch.object(sys, "argv", argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    cli.main()
        self.assertFalse((self.temp_dir / "eval.json").exists())

    def test_inline_model_patch_is_written_into_the_run_directory(self) -> None:
        manifest, predictions = self._write_inputs(
            CODE_SCENARIO, {CODE_ID: {"dry_run": True, "model_patch": "diff --git a/x b/x\n"}}
        )

        results = evaluate_predictions(manifest, predictions, self.temp_dir / "eval.json")

        item = results["results"][CODE_ID]
        patch_file = Path(item["result_path"]).parent / "model_patch.diff"
        self.assertEqual(patch_file.read_text(encoding="utf-8"), "diff --git a/x b/x\n")
        self.assertEqual(self._run_config(item)["code_patch_path"], str(patch_file))
        self.assertFalse((repo_root() / "temp_patches" / f"{CODE_ID}.diff").exists())


class AgentEvalScriptTests(unittest.TestCase):
    def test_default_outputs_are_keyed_by_profile(self) -> None:
        self.assertNotEqual(
            default_output("local_agent_eval", "configs/agents/claude_sonnet.example.json"),
            default_output("local_agent_eval", "configs/agents/openai_gpt41mini.example.json"),
        )

    def test_keep_artifacts_can_be_disabled(self) -> None:
        parser = build_parser()
        self.assertTrue(parser.parse_args(["--agent-config", "p.json"]).keep_artifacts)
        self.assertFalse(
            parser.parse_args(["--agent-config", "p.json", "--no-keep-artifacts"]).keep_artifacts
        )
