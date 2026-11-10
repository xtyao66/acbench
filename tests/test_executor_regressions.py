"""Regression tests for executor bugs: patch application, oracle protection,
test-output parsing, command execution, and ops grading."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from acbench.executors.backends.code.runner import parse_unittest_output
from acbench.executors.backends.code.standalone import (
    TIMEOUT_EXIT_CODE,
    apply_patch_without_git,
    capture_git_diff,
    normalize_command,
    run_commands,
    run_single_command,
)
from acbench.executors.backends.ops.engine import AgentDrivenOpsEngine
from acbench.executors.backends.ops.rubric import evaluate_problem
from acbench.executors.backends.ops.runtime import NativeOpsProblem, OpsRunRequest
from acbench.executors.local_code import (
    LocalCodeExecutor,
    canonical_test_id,
    forbidden_path_violations,
    patch_modified_paths,
)
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec

REPO_ROOT = Path(__file__).resolve().parents[1]
BILLING_SCENARIO = (
    REPO_ROOT / "tasks" / "scenarios" / "local" / "code"
    / "billing_pricing__bundle_discount_threshold.scenario.json"
)
# Rewrites the oracle assertion so the fail-to-pass test passes without a fix.
ORACLE_HUNK = (
    "@@ -24 +24 @@\n"
    "-        self.assertEqual(total, 2930)\n"
    "+        self.assertEqual(total, total)\n"
)


class _TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="acbench-regress-"))
        self.addCleanup(shutil.rmtree, self.temp_dir, True)

    def make_repo(self, files: dict[str, bytes]) -> Path:
        repo = self.temp_dir / "repo"
        for rel, content in files.items():
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        repo.mkdir(parents=True, exist_ok=True)
        return repo

    def apply(self, repo: Path, patch: str) -> tuple[bool, str]:
        patch_file = self.temp_dir / "change.diff"
        patch_file.write_bytes(patch.encode("utf-8"))
        return apply_patch_without_git(repo, patch_file)


class ForbiddenPathTests(_TempDirTestCase):
    def test_old_side_and_rename_paths_are_reported(self) -> None:
        git_style = (
            "diff --git a/tests/test_pricing.py b/src/pricing.py\n"
            "--- a/tests/test_pricing.py\n+++ b/src/pricing.py\n" + ORACLE_HUNK
        )
        plain = "--- a/tests/test_pricing.py\n+++ b/src/pricing.py\n" + ORACLE_HUNK
        rename = (
            "diff --git a/tests/t.py b/src/t.py\nsimilarity index 90%\n"
            "rename from tests/t.py\nrename to src/t.py\n"
        )
        for patch in (git_style, plain):
            self.assertIn("tests/test_pricing.py", patch_modified_paths(patch))
            self.assertTrue(forbidden_path_violations(patch_modified_paths(patch), ["tests/"]))
        self.assertEqual(patch_modified_paths(rename), ["tests/t.py", "src/t.py"])

    def test_escaping_and_case_variant_paths_are_violations(self) -> None:
        for path in ["../workspace/tests/test_x.py", "C:/repo/tests/test_x.py"]:
            self.assertEqual(forbidden_path_violations([path], ["tests/"]), [path])
        self.assertEqual(
            forbidden_path_violations(["Tests/test_x.py"], ["tests/"]),
            ["Tests/test_x.py"],
        )
        self.assertFalse(forbidden_path_violations(["src/app.py"], ["tests/"]))

    def test_executor_rejects_old_side_oracle_edit(self) -> None:
        scenario = ScenarioSpec.from_file(BILLING_SCENARIO)
        patch_file = self.temp_dir / "sneaky.diff"
        patch_file.write_text(
            "diff --git a/tests/test_pricing.py b/src/billing_pricing/pricing.py\n"
            "--- a/tests/test_pricing.py\n"
            "+++ b/src/billing_pricing/pricing.py\n" + ORACLE_HUNK,
            encoding="utf-8",
        )
        run_dir = self.temp_dir / "run"
        result = LocalCodeExecutor().execute(
            scenario, run_dir, RunConfig(dry_run=False, code_patch_path=str(patch_file))
        )
        self.assertTrue(result.details["forbidden_paths_violation"])
        self.assertFalse(result.success)
        self.assertEqual(result.fail_to_pass_success, [])
        oracle = (run_dir / "workspace" / "tests" / "test_pricing.py").read_text(encoding="utf-8")
        self.assertIn("assertEqual(total, 2930)", oracle)


class LenientApplierTests(_TempDirTestCase):
    def test_refuses_paths_outside_the_workspace(self) -> None:
        outside = self.temp_dir / "shared" / "app.py"
        outside.parent.mkdir(parents=True)
        outside.write_text("SECRET = 1\n", encoding="utf-8")
        repo = self.make_repo({"x.py": b"x = 1\n"})
        ok, output = self.apply(
            repo,
            "diff --git a/../shared/app.py b/../shared/app.py\n"
            "--- a/../shared/app.py\n+++ b/../shared/app.py\n"
            "@@ -1 +1 @@\n-SECRET = 1\n+SECRET = 2\n",
        )
        self.assertFalse(ok)
        self.assertIn("outside the workspace", output)
        self.assertEqual(outside.read_text(encoding="utf-8"), "SECRET = 1\n")

    def test_plain_multi_file_diff_patches_each_file(self) -> None:
        repo = self.make_repo({"a.py": b"x = 1\ny = 2\n", "b.py": b"p = 1\nq = 2\n"})
        ok, output = self.apply(
            repo,
            "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n-x = 1\n+x = 10\n y = 2\n"
            "--- a/b.py\n+++ b/b.py\n@@ -1,2 +1,2 @@\n-p = 1\n+p = 10\n q = 2\n",
        )
        self.assertTrue(ok, output)
        self.assertEqual((repo / "a.py").read_bytes(), b"x = 10\ny = 2\n")
        self.assertEqual((repo / "b.py").read_bytes(), b"p = 10\nq = 2\n")

    def test_no_prefix_diff_keeps_a_real_top_level_b_directory(self) -> None:
        repo = self.make_repo({"b/m.py": b"x = 1\n"})
        ok, output = self.apply(
            repo, "diff --git b/m.py b/m.py\n--- b/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
        )
        self.assertTrue(ok, output)
        self.assertEqual((repo / "b" / "m.py").read_bytes(), b"x = 2\n")

    def test_header_timestamp_is_ignored(self) -> None:
        repo = self.make_repo({"a.py": b"x = 1\n"})
        ok, output = self.apply(
            repo,
            "--- a/a.py\t2026-01-01 00:00:00.000000000 +0000\n"
            "+++ b/a.py\t2026-01-01 00:00:01.000000000 +0000\n"
            "@@ -1 +1 @@\n-x = 1\n+x = 2\n",
        )
        self.assertTrue(ok, output)
        self.assertEqual((repo / "a.py").read_bytes(), b"x = 2\n")

    def test_repeated_context_patches_the_declared_occurrence(self) -> None:
        source = b"def a():\n    total = 0\n    return total\n\ndef b():\n    total = 0\n    return total\n"
        repo = self.make_repo({"m.py": source})
        ok, output = self.apply(
            repo,
            "--- a/m.py\n+++ b/m.py\n@@ -6,2 +6,2 @@\n-    total = 0\n+    total = 100\n     return total\n",
        )
        self.assertTrue(ok, output)
        self.assertEqual(
            (repo / "m.py").read_text(encoding="utf-8").splitlines()[1:6],
            ["    total = 0", "    return total", "", "def b():", "    total = 100"],
        )

    def test_zero_context_deletion_uses_the_declared_line(self) -> None:
        repo = self.make_repo({"cfg.py": b"A = 1\nDEBUG = True\nB = 2\nDEBUG = True\n"})
        ok, output = self.apply(repo, "--- a/cfg.py\n+++ b/cfg.py\n@@ -4 +3,0 @@\n-DEBUG = True\n")
        self.assertTrue(ok, output)
        self.assertEqual((repo / "cfg.py").read_bytes(), b"A = 1\nDEBUG = True\nB = 2\n")

    def test_existing_lenient_behaviour_is_kept(self) -> None:
        # Semantic (line-less) hunk header -> first match; blank context line;
        # pure-addition hunk placed at its declared line.
        repo = self.make_repo({"m.py": b"a = 1\n\nb = 2\nc = 3\n"})
        ok, output = self.apply(
            repo,
            "--- a/m.py\n+++ b/m.py\n"
            "@@ def example(\n-a = 1\n+a = 10\n\n b = 2\n"
            "@@ -3,0 +4 @@\n+inserted = True\n",
        )
        self.assertTrue(ok, output)
        self.assertEqual(
            (repo / "m.py").read_bytes(), b"a = 10\n\nb = 2\ninserted = True\nc = 3\n"
        )

    def test_diff_against_a_scratch_copy_still_patches_in_place(self) -> None:
        # e.g. `diff -u foo.py foo.py.new`: no rename header, so foo.py is patched.
        repo = self.make_repo({"foo.py": b"x = 1\n"})
        ok, output = self.apply(repo, "--- foo.py\n+++ foo.py.new\n@@ -1 +1 @@\n-x = 1\n+x = 2\n")
        self.assertTrue(ok, output)
        self.assertEqual((repo / "foo.py").read_bytes(), b"x = 2\n")
        self.assertFalse((repo / "foo.py.new").exists())

    def test_new_file_patches_create_the_file(self) -> None:
        repo = self.make_repo({"a.py": b"x = 1\n"})
        ok, output = self.apply(
            repo,
            "diff --git a/pkg/helpers.py b/pkg/helpers.py\nnew file mode 100644\n"
            "index 0000000..1111111\n--- /dev/null\n+++ b/pkg/helpers.py\n"
            "@@ -0,0 +1,2 @@\n+def helper():\n+    return 1\n",
        )
        self.assertTrue(ok, output)
        self.assertEqual((repo / "pkg" / "helpers.py").read_bytes(), b"def helper():\n    return 1\n")
        ok, output = self.apply(repo, "--- /dev/null\n+++ b/extra.py\n@@ -0,0 +1 @@\n+y = 2\n")
        self.assertTrue(ok, output)
        self.assertEqual((repo / "extra.py").read_bytes(), b"y = 2\n")

    def test_delete_patches_remove_the_file(self) -> None:
        repo = self.make_repo({"old.py": b"x = 1\ny = 2\n", "gone.py": b"z = 3\n"})
        ok, output = self.apply(
            repo,
            "diff --git a/old.py b/old.py\ndeleted file mode 100644\nindex 1111111..0000000\n"
            "--- a/old.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-x = 1\n-y = 2\n",
        )
        self.assertTrue(ok, output)
        self.assertFalse((repo / "old.py").exists())
        ok, output = self.apply(repo, "--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-z = 3\n")
        self.assertTrue(ok, output)
        self.assertFalse((repo / "gone.py").exists())

    def test_rename_moves_and_edits_the_file(self) -> None:
        repo = self.make_repo({"old.py": b"x = 1\n"})
        ok, output = self.apply(
            repo,
            "diff --git a/old.py b/new.py\nsimilarity index 50%\nrename from old.py\n"
            "rename to new.py\n--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n",
        )
        self.assertTrue(ok, output)
        self.assertFalse((repo / "old.py").exists())
        self.assertEqual((repo / "new.py").read_bytes(), b"x = 2\n")

    def test_line_endings_and_final_newline_are_preserved(self) -> None:
        repo = self.make_repo(
            {"lf.py": b"x = 1\ny = 2\n", "crlf.py": b"x = 1\r\ny = 2\r\n", "bare.py": b"x = 1\ny = 2"}
        )
        hunk = "@@ -1,2 +1,2 @@\n-x = 1\n+x = 3\n y = 2\n"
        for name in ("lf.py", "crlf.py", "bare.py"):
            ok, output = self.apply(repo, f"--- a/{name}\n+++ b/{name}\n{hunk}")
            self.assertTrue(ok, output)
        self.assertEqual((repo / "lf.py").read_bytes(), b"x = 3\ny = 2\n")
        self.assertEqual((repo / "crlf.py").read_bytes(), b"x = 3\r\ny = 2\r\n")
        self.assertEqual((repo / "bare.py").read_bytes(), b"x = 3\ny = 2")

    def test_no_newline_marker_sets_the_final_newline(self) -> None:
        repo = self.make_repo({"a.py": b"x = 1\n", "b.py": b"y = 1"})
        ok, output = self.apply(
            repo,
            "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n\\ No newline at end of file\n"
            "--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-y = 1\n\\ No newline at end of file\n+y = 2\n",
        )
        self.assertTrue(ok, output)
        self.assertEqual((repo / "a.py").read_bytes(), b"x = 2")
        self.assertEqual((repo / "b.py").read_bytes(), b"y = 2\n")


class TestOutputParsingTests(unittest.TestCase):
    def test_pytest_node_ids_keep_their_directories(self) -> None:
        self.assertEqual(
            canonical_test_id("tests/unit/test_api.py::test_get"), "tests.unit.test_api.test_get"
        )

    def test_same_test_name_in_two_directories_is_not_credited_by_suffix(self) -> None:
        output = (
            "tests/unit/test_api.py::test_get FAILED  [ 50%]\n"
            "tests/integration/test_api.py::test_get PASSED  [100%]\n"
        )
        post = LocalCodeExecutor._parse_test_output(output)

        exact = LocalCodeExecutor._compare_statuses({}, post, ["tests/unit/test_api.py::test_get"], [])
        ambiguous = LocalCodeExecutor._compare_statuses({}, post, ["test_api.test_get"], [])

        self.assertEqual(exact[1], [])
        self.assertEqual(exact[3], ["tests/unit/test_api.py::test_get"])
        self.assertEqual(ambiguous[1], [])

    def test_pytest_node_ids_match_unittest_style_scenario_ids(self) -> None:
        output = "tests/test_handler.py::ScoreEventsTests::test_empty PASSED  [ 20%]\n"
        p2p_success, _, p2p_failure, _, validated = LocalCodeExecutor._compare_statuses(
            {},
            LocalCodeExecutor._parse_test_output(output),
            [],
            ["test_handler.ScoreEventsTests::test_empty"],
        )
        self.assertTrue(validated)
        self.assertEqual(p2p_success, ["test_handler.ScoreEventsTests::test_empty"])
        self.assertEqual(p2p_failure, [])

    def test_unittest_status_after_stderr_output_is_parsed(self) -> None:
        output = textwrap.dedent(
            """\
            test_other (test_app.AppTests.test_other) ... ok
            test_stamp (test_app.AppTests.test_stamp) ... C:\\src\\app.py:3: DeprecationWarning: utcnow() is deprecated
              return datetime.datetime.utcnow().year > 2000
            ok
            test_doc (test_app.AppTests.test_doc)
            Checks the documented case. ... FAIL

            ----------------------------------------------------------------------
            Ran 3 tests in 0.005s
            """
        )
        expected = {
            "test_app.AppTests.test_other::test_other": "pass",
            "test_app.AppTests.test_stamp::test_stamp": "pass",
            "test_app.AppTests.test_doc::test_doc": "fail",
        }
        self.assertEqual(parse_unittest_output(output), expected)
        self.assertEqual(LocalCodeExecutor._parse_unittest_output(output), expected)


class CommandExecutionTests(_TempDirTestCase):
    EXE = r"C:\Py\python.exe"

    def normalize_on_windows(self, command: str) -> tuple[str, dict[str, str]]:
        with mock.patch("acbench.executors.backends.code.standalone.os.name", "nt"):
            with mock.patch("acbench.executors.backends.code.standalone.sys.executable", self.EXE):
                return normalize_command(command)

    def test_windows_env_prefixed_python_uses_this_interpreter(self) -> None:
        self.assertEqual(
            self.normalize_on_windows("$env:PYTHONPATH='src'; python -m unittest -v"),
            (f"$env:PYTHONPATH='src'; & \"{self.EXE}\" -m unittest -v", {}),
        )
        self.assertEqual(
            self.normalize_on_windows("PYTHONPATH=src python -m pytest tests/ -q"),
            (f'& "{self.EXE}" -m pytest tests/ -q', {"PYTHONPATH": "src"}),
        )
        # Non-python commands are left alone.
        self.assertEqual(self.normalize_on_windows("go test ./..."), ("go test ./...", {}))

    def test_timeout_kills_the_process_tree(self) -> None:
        # The child spawns a grandchild that inherits the output pipes; returning
        # promptly proves the whole tree was killed, not just the shell.
        script = (
            "import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
            "time.sleep(120)"
        )
        started = time.monotonic()
        result = run_single_command(f'python -c "{script}"', self.temp_dir, timeout=3)
        self.assertLess(time.monotonic() - started, 60)
        self.assertEqual(result.returncode, TIMEOUT_EXIT_CODE)
        self.assertIn("timed out", result.stderr)
        ok, output = run_commands(['python -c "import time; time.sleep(120)"'], self.temp_dir, timeout=3)
        self.assertFalse(ok)
        self.assertIn(f"exit_code={TIMEOUT_EXIT_CODE}", output)

    def test_interrupt_kills_the_process_tree_before_propagating(self) -> None:
        with mock.patch(
            "subprocess.Popen.communicate", side_effect=KeyboardInterrupt
        ), mock.patch(
            "acbench.executors.backends.code.standalone._kill_process_tree"
        ) as kill:
            with self.assertRaises(KeyboardInterrupt):
                run_single_command('python -c "pass"', self.temp_dir, timeout=30)
        kill.assert_called_once()

    def test_executor_passes_scenario_runtime_budget(self) -> None:
        scenario = ScenarioSpec.from_file(BILLING_SCENARIO)
        with mock.patch(
            "acbench.executors.local_code.run_commands", return_value=(True, "")
        ) as fake_run:
            LocalCodeExecutor().execute(scenario, self.temp_dir / "run", RunConfig(dry_run=False))
        budget = scenario.constraints.max_runtime_minutes * 60
        self.assertTrue(fake_run.call_args_list)
        for call in fake_run.call_args_list:
            self.assertEqual(call.kwargs["timeout"], budget)

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_git_diff_ignores_an_enclosing_repository(self) -> None:
        outer = self.temp_dir / "outer"
        workspace = outer / "runs" / "r1" / "workspace"
        workspace.mkdir(parents=True)
        (outer / "unrelated.txt").write_text("v1\n", encoding="utf-8")
        git = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "core.autocrlf=false"]
        subprocess.run(git + ["init", "-q"], cwd=outer, check=True)
        subprocess.run(git + ["add", "unrelated.txt"], cwd=outer, check=True)
        subprocess.run(git + ["commit", "-qm", "init"], cwd=outer, check=True)
        (outer / "unrelated.txt").write_text("v2\n", encoding="utf-8")
        self.assertEqual(capture_git_diff(workspace), "")
        # A workspace that is its own repository root is still diffed.
        self.assertIn("unrelated.txt", capture_git_diff(outer))


class _EmptyOpsAgent:
    """Ops agent that returns an empty assessment."""

    def analyze(self, problem, *, output_dir: Path) -> dict[str, object]:
        return {"assessment": {"summary": "", "root_cause": "", "remediation": "", "evidence": []}}


class _KeywordOpsAgent:
    """Ops agent that states every expected keyword."""

    def analyze(self, problem, *, output_dir: Path) -> dict[str, object]:
        text = " ".join(
            problem.detection_keywords + problem.localization_keywords + problem.repair_keywords
        )
        return {"assessment": {"summary": text, "root_cause": text, "remediation": text}}


class OpsGradingTests(unittest.TestCase):
    def run_engine(self, problem: NativeOpsProblem, agent: str):
        with tempfile.TemporaryDirectory() as tmp_dir:
            return AgentDrivenOpsEngine().run(
                OpsRunRequest(
                    problem=problem,
                    output_dir=Path(tmp_dir),
                    agent_ref=f"tests.test_executor_regressions:{agent}",
                )
            )

    def problem(self, **keywords) -> NativeOpsProblem:
        return NativeOpsProblem(
            problem_id="p-leak",
            source="acbench",
            application="cache",
            service="redis-session",
            error_logs=["evicted sessions; 401 session not found"],
            require_detection=True,
            require_localization=True,
            require_repair=True,
            **keywords,
        )

    def test_all_leaked_required_stages_never_succeed(self) -> None:
        problem = self.problem(
            detection_keywords=["evicted"],
            localization_keywords=["redis-session"],
            repair_keywords=["session not found"],
        )
        outcome = self.run_engine(problem, "_EmptyOpsAgent")
        self.assertFalse(outcome.success)
        self.assertEqual((outcome.detected, outcome.localized, outcome.repaired), (False, False, False))

    def test_leaked_stage_earns_no_credit_but_does_not_block_others(self) -> None:
        problem = self.problem(
            detection_keywords=["evicted"],  # leaked via the error log
            localization_keywords=["maxmemory policy"],
            repair_keywords=["volatile-lru"],
        )
        outcome = self.run_engine(problem, "_KeywordOpsAgent")
        self.assertTrue(outcome.success)
        self.assertFalse(outcome.detected)
        self.assertTrue(outcome.localized)
        self.assertTrue(outcome.repaired)

    def test_service_name_shown_in_prompt_counts_as_leaked(self) -> None:
        problem = self.problem(localization_keywords=["redis-session", "maxmemory policy"])
        rubric = evaluate_problem(problem, {"root_cause": "the problem is in redis-session"})
        self.assertEqual(rubric["localization"].leaked, ["redis-session"])
        self.assertEqual(rubric["localization"].recall, 0.0)
        self.assertFalse(rubric["localization"].passed)


if __name__ == "__main__":
    unittest.main()
