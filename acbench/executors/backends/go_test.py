"""Go execution backend for the ACBench code-repair grading contract.

This backend mirrors the Python (pytest/unittest) grading path implemented in
``acbench.executors.local_code``: given a repository with the agent patch
already applied on disk and the scenario's FAIL_TO_PASS / PASS_TO_PASS test
ids, it runs ``go test`` and returns the SAME per-test status structure the
Python path produces, so ``_compare_statuses`` can grade Go and Python
identically.

Test ids for Go scenarios use the canonical form::

    <import/path/of/package>.<TestName>

e.g. ``github.com/prometheus/prometheus/tsdb.TestSummaryNoQuantilesNoPanic``.
The shorter form ``<package-basename>.<TestName>`` (``tsdb.TestSummary...``)
is also accepted. ``go test -json`` reports the full package import path in the
``Package`` field and the bare ``TestName`` in the ``Test`` field; we join them
with ``.`` and feed the result through the shared ``canonical_test_id`` so the
matching logic is byte-for-byte the same as the Python backend.

Design constraints (kept identical to the Python path):

* No silent passes — a test id that never appears in the JSON stream (typo,
  build failure, package mismatch) is recorded as ``fail``, never dropped.
* Test ids are validated before being handed to ``go test -run``; malformed
  ids raise rather than being quietly skipped.
* Forbidden-path / patch-application logic is reused from the shared helpers
  rather than duplicated.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from typing import Any

# Reuse the Python-path helpers verbatim so the two backends cannot drift apart.
from acbench.executors.backends.code.standalone import run_single_command
from acbench.executors.local_code import (
    canonical_test_id,
    forbidden_path_violations,
    patch_modified_paths,
)

__all__ = [
    "GoTestRunner",
    "go_test_name",
    "parse_go_test_json",
    "validate_go_test_id",
]


# A Go test function is an exported identifier beginning with ``Test``.
# (Examples / benchmarks / fuzz targets are not graded here.)
_GO_TEST_NAME_RE = re.compile(r"^Test[A-Za-z0-9_]*$")


def go_test_name(test_id: str) -> str:
    """Return the bare Go ``TestName`` for a scenario test id.

    The scenario id is ``<package>.<TestName>``; ``go test -run`` only matches
    on the function name, so we extract the trailing identifier. Sub-test
    suffixes (``TestFoo/case_one``) are preserved up to the first ``/`` for the
    ``-run`` anchor but matched at the parent-test granularity, which is what
    ``go test -json`` reports a pass/fail for.
    """

    last = canonical_test_id(test_id).split(".")[-1]
    return last.split("/", 1)[0]


def validate_go_test_id(test_id: str) -> str:
    """Validate a Go scenario test id and return its bare ``TestName``.

    Raises ``ValueError`` for ids whose trailing component is not a well-formed
    Go test function name. This is the Go analogue of the defensive id
    validation the Python path performs via ``canonical_test_id`` — a malformed
    oracle id must surface loudly, never be silently skipped (which would let a
    broken scenario "pass" by grading zero tests).
    """

    name = go_test_name(test_id)
    if not _GO_TEST_NAME_RE.match(name):
        raise ValueError(
            f"Invalid Go test id {test_id!r}: trailing name {name!r} is not a "
            "valid Go test function (expected /^Test[A-Za-z0-9_]*$/)."
        )
    return name


def _canonical_keys(package: str, test: str) -> set[str]:
    """Return every canonical key a (package, test) event should match.

    ``go test -json`` reports the *full import path* in ``Package`` (e.g.
    ``github.com/prometheus/prometheus/tsdb``). Scenario ids may use that full
    path or just the package basename, so we register both canonical forms.
    """

    package = (package or "").strip().strip("/")
    test = (test or "").strip()
    keys: set[str] = set()
    if not test:
        return keys
    if package:
        keys.add(canonical_test_id(f"{package}.{test}"))
        basename = package.rsplit("/", 1)[-1]
        if basename and basename != package:
            keys.add(canonical_test_id(f"{basename}.{test}"))
    keys.add(canonical_test_id(test))
    return keys


def parse_go_test_json(output: str) -> dict[str, str]:
    """Parse a ``go test -json`` event stream into per-test pass/fail statuses.

    ``go test -json`` emits one JSON object per line. We care about events that
    carry a ``Test`` field with a terminal ``Action`` of ``pass`` / ``fail`` /
    ``skip``. Each test is keyed by every canonical form derived from its
    package + name (see ``_canonical_keys``) so the result can be matched
    against scenario ids regardless of whether they use the full import path or
    the package basename.

    Mirrors ``_parse_pytest_output``: ``pass`` -> ``"pass"``,
    ``skip`` -> ``"skip"``, everything terminal else -> ``"fail"``. Non-JSON
    lines (e.g. raw build errors ``go`` prints before the stream) are ignored
    for parsing but do NOT produce a pass — an absent test stays absent and is
    graded ``fail`` downstream.
    """

    statuses: dict[str, str] = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        test = event.get("Test")
        action = event.get("Action")
        if not test or action not in {"pass", "fail", "skip"}:
            continue
        if action == "pass":
            status = "pass"
        elif action == "skip":
            status = "skip"
        else:
            status = "fail"
        for key in _canonical_keys(str(event.get("Package", "")), str(test)):
            # A later terminal event for the same test wins, except a recorded
            # failure is never downgraded to pass (defensive against a parent
            # "pass" arriving after a sub-test "fail" in odd interleavings).
            if statuses.get(key) == "fail" and status != "fail":
                continue
            statuses[key] = status
    return statuses


class GoTestRunner:
    """Run Go tests for a prepared workspace and grade against scenario ids.

    The patch is assumed to be applied on disk already (the caller — the
    language-dispatching executor — handles patch application and
    forbidden-path rejection using the shared helpers). This class is the Go
    analogue of the pytest invocation + ``_parse_test_output`` step.
    """

    def __init__(self, go_binary: str = "go") -> None:
        self._go_binary = go_binary

    # -- patch helpers (reuse shared logic; do not duplicate) ---------------

    @staticmethod
    def patch_modified_paths(patch_text: str) -> list[str]:
        """Repo-relative paths a unified diff touches (shared with Python path)."""

        return patch_modified_paths(patch_text)

    @staticmethod
    def forbidden_path_violations(
        modified: list[str], forbidden: list[str]
    ) -> list[str]:
        """Forbidden-path check (shared, canonicalizing helper)."""

        return forbidden_path_violations(modified, forbidden)

    # -- test execution -----------------------------------------------------

    def is_available(self) -> bool:
        """Return True when the configured ``go`` binary is on PATH."""

        return shutil.which(self._go_binary) is not None

    def build_run_pattern(self, test_ids: list[str]) -> str:
        """Build a single ``-run`` regex anchoring all requested test names.

        ``go test -run`` takes one regex; we OR the validated bare test names
        together (``^(TestA|TestB)$``) so a single invocation can drive every
        FAIL_TO_PASS + PASS_TO_PASS test. Each id is validated first.
        """

        names: list[str] = []
        for test_id in test_ids:
            name = validate_go_test_id(test_id)
            if name not in names:
                names.append(name)
        if not names:
            return ""
        return "^(" + "|".join(re.escape(n) for n in names) + ")$"

    def run_tests(
        self,
        repo_root: str | Path,
        fail_to_pass: list[str],
        pass_to_pass: list[str],
        *,
        package_pattern: str = "./...",
        extra_args: list[str] | None = None,
    ) -> tuple[dict[str, str], str]:
        """Run ``go test -json`` for the requested ids; return (statuses, log).

        ``statuses`` is the same shape ``_parse_test_output`` returns for the
        Python path (canonical id -> ``"pass"`` / ``"fail"`` / ``"skip"``) and
        can be passed straight into ``_compare_statuses``. ``log`` is the raw
        combined command output for the run artifact.

        Every requested id is validated up front, so a malformed oracle id
        raises rather than silently grading zero tests.
        """

        repo_root = Path(repo_root)
        all_ids = list(fail_to_pass) + list(pass_to_pass)
        run_pattern = self.build_run_pattern(all_ids)

        command_parts = [self._go_binary, "test", "-json"]
        if run_pattern:
            command_parts += ["-run", run_pattern]
        command_parts.append(package_pattern)
        if extra_args:
            command_parts += list(extra_args)
        command = " ".join(_shell_quote(p) for p in command_parts)

        result = run_single_command(command, repo_root)
        combined = f"{result.stdout}{result.stderr}"
        log = f"$ {command}\n{combined}\nexit_code={result.returncode}\n"

        statuses = parse_go_test_json(combined)
        return statuses, log

    def grade(
        self,
        repo_root: str | Path,
        fail_to_pass: list[str],
        pass_to_pass: list[str],
        *,
        package_pattern: str = "./...",
        extra_args: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run the tests and return a status dict mirroring the Python path.

        The returned dict matches the fields ``LocalCodeExecutor`` surfaces for
        the code stage so a caller can build an ``ExecutorResult`` uniformly::

            {
              "post_patch_status": {<canonical id>: "pass"|"fail"|"skip"},
              "fail_to_pass_success": [...], "fail_to_pass_failure": [...],
              "pass_to_pass_success": [...], "pass_to_pass_failure": [...],
              "id_validated": True,
              "test_success": bool,   # all FAIL_TO_PASS pass, no PASS_TO_PASS regress
              "resolved": bool,       # SWE-bench "resolved" alias of test_success
              "log": "<raw go test output>",
            }
        """

        statuses, log = self.run_tests(
            repo_root,
            fail_to_pass,
            pass_to_pass,
            package_pattern=package_pattern,
            extra_args=extra_args,
        )

        post_canonical = {canonical_test_id(k): v for k, v in statuses.items()}

        def passed(test_id: str) -> bool:
            return post_canonical.get(canonical_test_id(test_id)) == "pass"

        fail_to_pass_success = [t for t in fail_to_pass if passed(t)]
        fail_to_pass_failure = [t for t in fail_to_pass if not passed(t)]
        pass_to_pass_success = [t for t in pass_to_pass if passed(t)]
        pass_to_pass_failure = [t for t in pass_to_pass if not passed(t)]

        resolved = not fail_to_pass_failure and not pass_to_pass_failure
        return {
            "post_patch_status": statuses,
            "fail_to_pass_success": fail_to_pass_success,
            "fail_to_pass_failure": fail_to_pass_failure,
            "pass_to_pass_success": pass_to_pass_success,
            "pass_to_pass_failure": pass_to_pass_failure,
            "id_validated": True,
            "test_success": resolved,
            "resolved": resolved,
            "log": log,
        }


def _shell_quote(part: str) -> str:
    """Quote a single command token for the shell-based runner.

    ``run_single_command`` executes via ``shell=True``; the ``-run`` regex
    contains ``^``, ``|``, ``(`` and ``$`` which must survive the shell. We use
    POSIX-style single-quoting (the runner already special-cases Windows for
    its own commands; Go scenarios target POSIX CI).
    """

    if part and re.fullmatch(r"[A-Za-z0-9_./:=-]+", part):
        return part
    return "'" + part.replace("'", "'\\''") + "'"
