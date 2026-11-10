"""Tests for the local code executor."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from acbench.executors.local_code import LocalCodeExecutor
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec


class LocalCodeExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="acbench-local-code-"))
        self.repo_dir = self.temp_dir / "repo"
        self.run_dir = self.temp_dir / "run"
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_local_executor_writes_logs(self) -> None:
        scenario = ScenarioSpec.from_dict(
            {
                "scenario_id": "local-code-pass",
                "title": "local code pass",
                "mode": "code_only",
                "service": {
                    "application": "app",
                    "service": "svc",
                    "repository_path": str(self.repo_dir),
                },
                "code_fault": {
                    "source": "acbench",
                    "defect_id": "d1",
                },
                "build": {
                    "rebuild_cmds": ['python -c "print(\'build-ok\')"'],
                    "test_cmds": ['python -c "print(\'test-ok\')"'],
                },
                "success_criteria": {
                    "require_build_success": True,
                    "require_test_success": True,
                    "require_repair": True,
                },
            }
        )

        result = LocalCodeExecutor().execute(
            scenario,
            self.run_dir,
            RunConfig(dry_run=False, max_steps=3),
        )

        self.assertTrue(result.success)
        self.assertTrue(Path(result.logs["build_log_path"]).exists())
        self.assertTrue(Path(result.logs["test_log_path"]).exists())

    def test_local_executor_applies_patch_file(self) -> None:
        fixture_repo = (
            Path(__file__).resolve().parents[1]
            / "services"
            / "fixtures"
            / "billing_pricing_buggy"
        )
        scenario = ScenarioSpec.from_dict(
            {
                "scenario_id": "local-code-patch",
                "title": "local code patch",
                "mode": "code_only",
                "service": {
                    "application": "fixture",
                    "service": "billing-pricing",
                    "repository_path": str(fixture_repo),
                },
                "code_fault": {
                    "source": "acbench",
                    "defect_id": "d2",
                },
                "build": {
                    "rebuild_cmds": ["python -m compileall src"],
                    "test_cmds": [
                        "$env:PYTHONPATH='src'; python -m unittest discover -s tests -p \"test_*.py\" -v"
                    ],
                },
                "success_criteria": {
                    "require_build_success": True,
                    "require_test_success": True,
                    "require_repair": True,
                },
            }
        )

        result = LocalCodeExecutor().execute(
            scenario,
            self.run_dir,
            RunConfig(
                dry_run=False,
                max_steps=3,
                code_patch_path=str(
                    Path(__file__).resolve().parents[1]
                    / "patches"
                    / "billing_pricing_bundle_fix.diff"
                ),
            ),
        )

        self.assertTrue(result.success)
        self.assertTrue(result.details["apply_success"])
        self.assertTrue(Path(result.logs["apply_log_path"]).exists())
        self.assertEqual(len(result.fail_to_pass_success), 1)
        self.assertEqual(len(result.pass_to_pass_success), 2)
