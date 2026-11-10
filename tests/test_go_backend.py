"""Tests for the Go execution backend.

Two layers:

* ``GoTestParserTests`` / ``GoTestIdTests`` / ``GoTestRunnerGradeTests`` always
  run — they validate the ``go test -json`` parser, id validation, and the
  grading contract against captured sample output, so the logic is covered even
  on machines without a Go toolchain.
* ``GoBackendIntegrationTests`` builds a tiny real Go module (a failing test
  that flips to passing after a one-line source fix) and is skipped unless
  ``go`` is installed.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from acbench.executors.backends.go_test import (
    GoTestRunner,
    go_test_name,
    parse_go_test_json,
    validate_go_test_id,
)
from acbench.executors.local_code import LocalCodeExecutor
from acbench.models.scenario import ScenarioSpec
from acbench.models.runtime import RunConfig


# A realistic captured ``go test -json`` event stream: one passing target test,
# one failing test, one skipped test, plus the package-level summary event that
# carries no ``Test`` field (must be ignored). Output lines are interleaved as
# the real tool emits them.
SAMPLE_GO_TEST_JSON = "\n".join(
    [
        '{"Time":"2026-06-18T00:00:00Z","Action":"start","Package":"github.com/acme/widget"}',
        '{"Time":"2026-06-18T00:00:00Z","Action":"run","Package":"github.com/acme/widget","Test":"TestAdd"}',
        '{"Time":"2026-06-18T00:00:00Z","Action":"output","Package":"github.com/acme/widget","Test":"TestAdd","Output":"=== RUN   TestAdd\\n"}',
        '{"Time":"2026-06-18T00:00:00Z","Action":"output","Package":"github.com/acme/widget","Test":"TestAdd","Output":"--- PASS: TestAdd (0.00s)\\n"}',
        '{"Time":"2026-06-18T00:00:00Z","Action":"pass","Package":"github.com/acme/widget","Test":"TestAdd","Elapsed":0.0}',
        '{"Time":"2026-06-18T00:00:00Z","Action":"run","Package":"github.com/acme/widget","Test":"TestSub"}',
        '{"Time":"2026-06-18T00:00:00Z","Action":"output","Package":"github.com/acme/widget","Test":"TestSub","Output":"    widget_test.go:20: got 3 want 1\\n"}',
        '{"Time":"2026-06-18T00:00:00Z","Action":"fail","Package":"github.com/acme/widget","Test":"TestSub","Elapsed":0.0}',
        '{"Time":"2026-06-18T00:00:00Z","Action":"skip","Package":"github.com/acme/widget","Test":"TestFlaky","Elapsed":0.0}',
        # Non-JSON noise the tool can interleave on build issues — must be ignored.
        "# github.com/acme/widget [build failed]",
        '{"Time":"2026-06-18T00:00:00Z","Action":"fail","Package":"github.com/acme/widget","Elapsed":0.01}',
    ]
)


class GoTestIdTests(unittest.TestCase):
    def test_go_test_name_extracts_trailing_identifier(self) -> None:
        self.assertEqual(
            go_test_name("github.com/acme/widget.TestAdd"),
            "TestAdd",
        )
        self.assertEqual(go_test_name("widget.TestAdd"), "TestAdd")
        self.assertEqual(go_test_name("TestAdd"), "TestAdd")

    def test_go_test_name_strips_subtest_suffix(self) -> None:
        self.assertEqual(go_test_name("pkg.TestAdd/case_one"), "TestAdd")

    def test_validate_accepts_valid_ids(self) -> None:
        self.assertEqual(
            validate_go_test_id("github.com/acme/widget.TestAdd"), "TestAdd"
        )

    def test_validate_rejects_non_test_identifier(self) -> None:
        with self.assertRaises(ValueError):
            validate_go_test_id("github.com/acme/widget.helperFunc")

    def test_validate_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            validate_go_test_id("github.com/acme/widget.")


class GoTestParserTests(unittest.TestCase):
    def test_parse_registers_full_basename_and_bare_keys(self) -> None:
        statuses = parse_go_test_json(SAMPLE_GO_TEST_JSON)
        # Full import path, package basename, and bare-name forms all map to pass.
        self.assertEqual(statuses["github.com/acme/widget.TestAdd"], "pass")
        self.assertEqual(statuses["widget.TestAdd"], "pass")
        self.assertEqual(statuses["TestAdd"], "pass")

    def test_parse_marks_failing_test_fail(self) -> None:
        statuses = parse_go_test_json(SAMPLE_GO_TEST_JSON)
        self.assertEqual(statuses["github.com/acme/widget.TestSub"], "fail")

    def test_parse_marks_skipped_test_skip(self) -> None:
        statuses = parse_go_test_json(SAMPLE_GO_TEST_JSON)
        self.assertEqual(statuses["github.com/acme/widget.TestFlaky"], "skip")

    def test_parse_ignores_package_level_and_non_json(self) -> None:
        statuses = parse_go_test_json(SAMPLE_GO_TEST_JSON)
        # The package-level fail event (no "Test") must not create a bogus key.
        self.assertNotIn("github.com/acme/widget", statuses)
        # Exactly three distinct tests were reported.
        bare = {k for k in statuses if "." not in k}
        self.assertEqual(bare, {"TestAdd", "TestSub", "TestFlaky"})

    def test_absent_test_is_not_passed(self) -> None:
        # A test id never seen in the stream must not be graded "pass".
        statuses = parse_go_test_json(SAMPLE_GO_TEST_JSON)
        self.assertNotIn("TestNeverRan", statuses)


class GoTestRunnerGradeTests(unittest.TestCase):
    """Grade contract checks driven by a stubbed test run (no Go toolchain)."""

    def _runner_with_output(self, output: str) -> GoTestRunner:
        runner = GoTestRunner()
        runner.run_tests = lambda *a, **k: (parse_go_test_json(output), output)  # type: ignore[assignment]
        return runner

    def test_grade_resolves_when_f2p_passes_and_p2p_holds(self) -> None:
        runner = self._runner_with_output(SAMPLE_GO_TEST_JSON)
        result = runner.grade(
            repo_root=".",
            fail_to_pass=["github.com/acme/widget.TestAdd"],
            pass_to_pass=[],
        )
        self.assertTrue(result["resolved"])
        self.assertTrue(result["test_success"])
        self.assertEqual(result["fail_to_pass_success"], ["github.com/acme/widget.TestAdd"])
        self.assertEqual(result["fail_to_pass_failure"], [])

    def test_grade_not_resolved_when_f2p_fails(self) -> None:
        runner = self._runner_with_output(SAMPLE_GO_TEST_JSON)
        result = runner.grade(
            repo_root=".",
            fail_to_pass=["github.com/acme/widget.TestSub"],
            pass_to_pass=[],
        )
        self.assertFalse(result["resolved"])
        self.assertEqual(result["fail_to_pass_failure"], ["github.com/acme/widget.TestSub"])

    def test_grade_no_silent_pass_for_missing_test(self) -> None:
        # An oracle id that never appears in the stream must grade as failure,
        # never silently pass.
        runner = self._runner_with_output(SAMPLE_GO_TEST_JSON)
        result = runner.grade(
            repo_root=".",
            fail_to_pass=["github.com/acme/widget.TestNeverRan"],
            pass_to_pass=[],
        )
        self.assertFalse(result["resolved"])
        self.assertEqual(
            result["fail_to_pass_failure"], ["github.com/acme/widget.TestNeverRan"]
        )

    def test_grade_p2p_regression_blocks_resolution(self) -> None:
        runner = self._runner_with_output(SAMPLE_GO_TEST_JSON)
        result = runner.grade(
            repo_root=".",
            fail_to_pass=["github.com/acme/widget.TestAdd"],
            pass_to_pass=["github.com/acme/widget.TestSub"],  # actually fails
        )
        self.assertFalse(result["resolved"])
        self.assertEqual(
            result["pass_to_pass_failure"], ["github.com/acme/widget.TestSub"]
        )

    def test_build_run_pattern_validates_and_anchors(self) -> None:
        runner = GoTestRunner()
        pattern = runner.build_run_pattern(
            ["pkg.TestAdd", "pkg.TestSub", "pkg.TestAdd"]
        )
        self.assertEqual(pattern, "^(TestAdd|TestSub)$")

    def test_build_run_pattern_raises_on_bad_id(self) -> None:
        runner = GoTestRunner()
        with self.assertRaises(ValueError):
            runner.build_run_pattern(["pkg.notATest"])


def _write_go_module(root: Path, *, buggy: bool) -> None:
    """Write a minimal Go module with one source func and one test.

    When ``buggy`` is True, ``Sub`` is wrong so ``TestSub`` FAILS. The fix
    flips ``+`` back to ``-`` so the FAIL_TO_PASS test passes.
    """

    (root / "go.mod").write_text("module example.com/widget\n\ngo 1.21\n", encoding="utf-8")
    sub_body = "    return a + b\n" if buggy else "    return a - b\n"
    (root / "widget.go").write_text(
        "package widget\n\n"
        "func Add(a, b int) int {\n    return a + b\n}\n\n"
        "func Sub(a, b int) int {\n" + sub_body + "}\n",
        encoding="utf-8",
    )
    (root / "widget_test.go").write_text(
        "package widget\n\n"
        "import \"testing\"\n\n"
        "func TestAdd(t *testing.T) {\n"
        "    if Add(2, 1) != 3 {\n        t.Fatalf(\"Add broken\")\n    }\n}\n\n"
        "func TestSub(t *testing.T) {\n"
        "    if got := Sub(2, 1); got != 1 {\n"
        "        t.Fatalf(\"Sub: got %d want 1\", got)\n    }\n}\n",
        encoding="utf-8",
    )


@unittest.skipUnless(shutil.which("go"), "go not installed")
class GoBackendIntegrationTests(unittest.TestCase):
    """End-to-end: a real failing Go test flips to pass after a source fix."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="acbench-go-backend-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_fail_to_pass_flips_after_fix(self) -> None:
        repo = self.temp_dir / "buggy"
        repo.mkdir()
        _write_go_module(repo, buggy=True)

        runner = GoTestRunner()
        f2p = ["example.com/widget.TestSub"]
        p2p = ["example.com/widget.TestAdd"]

        before = runner.grade(str(repo), fail_to_pass=f2p, pass_to_pass=p2p)
        self.assertFalse(before["resolved"], before["log"])
        self.assertEqual(before["fail_to_pass_failure"], f2p)
        # The PASS_TO_PASS test should already pass on the buggy tree.
        self.assertEqual(before["pass_to_pass_success"], p2p)

        # Apply the one-line fix (the agent patch, here applied directly).
        _write_go_module(repo, buggy=False)

        after = runner.grade(str(repo), fail_to_pass=f2p, pass_to_pass=p2p)
        self.assertTrue(after["resolved"], after["log"])
        self.assertEqual(after["fail_to_pass_success"], f2p)
        self.assertEqual(after["pass_to_pass_success"], p2p)

    def test_language_dispatch_through_local_code_executor(self) -> None:
        """LocalCodeExecutor infers 'go' from go.mod and grades with the Go parser."""

        repo = self.temp_dir / "exec_repo"
        repo.mkdir()
        _write_go_module(repo, buggy=False)
        run_dir = self.temp_dir / "run"
        run_dir.mkdir()

        scenario = ScenarioSpec.from_dict(
            {
                "scenario_id": "go-dispatch",
                "title": "go dispatch",
                "mode": "code_only",
                "service": {
                    "application": "app",
                    "service": "svc",
                    "repository_path": str(repo),
                },
                "code_fault": {"source": "acbench", "defect_id": "g1"},
                "build": {
                    # language omitted on purpose -> inferred from go.mod
                    "test_cmds": [
                        "go test -json -run '^(TestSub|TestAdd)$' ./..."
                    ],
                },
                "evaluation": {
                    "fail_to_pass": ["example.com/widget.TestSub"],
                    "pass_to_pass": ["example.com/widget.TestAdd"],
                },
                "success_criteria": {"require_test_success": True},
            }
        )

        result = LocalCodeExecutor().execute(
            scenario, run_dir, RunConfig(dry_run=False, max_steps=3)
        )
        self.assertEqual(result.details["language"], "go")
        self.assertTrue(result.success, result.logs)
        self.assertEqual(result.fail_to_pass_success, ["example.com/widget.TestSub"])
        self.assertEqual(result.pass_to_pass_success, ["example.com/widget.TestAdd"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
