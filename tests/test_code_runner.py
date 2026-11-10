"""Tests for the standalone internal code runner."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from acbench.executors.backends.code.runner import (
    compare_statuses,
    parse_unittest_output,
    run_local_code_request,
)
from acbench.executors.backends.code.runtime import CodeRunRequest, NativeCodeInstance


class CodeRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="acbench-code-runner-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_unittest_output_extracts_statuses(self) -> None:
        output = (
            "test_addition_simple (test_calculator.CalculatorTests) ... FAIL\n"
            "test_addition_with_zero (test_calculator.CalculatorTests) ... ok\n"
        )
        statuses = parse_unittest_output(output)
        self.assertEqual(
            statuses["test_calculator.CalculatorTests::test_addition_simple"],
            "fail",
        )
        self.assertEqual(
            statuses["test_calculator.CalculatorTests::test_addition_with_zero"],
            "pass",
        )

    def test_compare_statuses_computes_pass_and_fail_buckets(self) -> None:
        result = compare_statuses(
            {"a": "pass", "b": "fail"},
            {"a": "pass", "b": "pass"},
        )
        self.assertEqual(result[0], ["a"])
        self.assertEqual(result[1], ["b"])
        self.assertEqual(result[2], [])
        self.assertEqual(result[3], [])

    def test_run_local_code_request_resolves_fixture_with_gold_patch(self) -> None:
        fixture_repo = (
            Path(__file__).resolve().parents[1]
            / "services"
            / "fixtures"
            / "billing_pricing_buggy"
        )
        patch_path = (
            Path(__file__).resolve().parents[1]
            / "patches"
            / "billing_pricing_bundle_fix.diff"
        )
        outcome = run_local_code_request(
            CodeRunRequest(
                instance=NativeCodeInstance(
                    instance_id="fixture-1",
                    repo=str(fixture_repo),
                    platform="windows",
                    patch=patch_path.read_text(encoding="utf-8"),
                    pred_patch=patch_path.read_text(encoding="utf-8"),
                    test_patch="",
                    rebuild_cmds=["python -m compileall src"],
                    test_cmds=[
                        "$env:PYTHONPATH='src'; python -m unittest discover -s tests -p \"test_*.py\" -v"
                    ],
                    pass_to_pass=[],
                    fail_to_pass=[],
                ),
                output_dir=self.temp_dir / "run",
            )
        )

        self.assertTrue(outcome.resolved)
        self.assertEqual(len(outcome.fail_to_pass_success), 1)
        self.assertEqual(len(outcome.pass_to_pass_success), 2)
        self.assertTrue(Path(outcome.logs["build_log_path"]).exists())
        self.assertTrue(Path(outcome.logs["test_log_path"]).exists())


if __name__ == "__main__":
    unittest.main()
