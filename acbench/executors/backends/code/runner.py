"""Standalone code-task runner for the internal ACBench code backend."""

from __future__ import annotations

from pathlib import Path
import re

from acbench.executors.backends.code.runtime import CodeRunOutcome, CodeRunRequest
from acbench.executors.backends.code.standalone import (
    apply_patch,
    capture_git_diff,
    prepare_workspace,
    run_commands,
)


def run_local_code_request(request: CodeRunRequest) -> CodeRunOutcome:
    """Run one local-repository code request using ACBench-owned primitives."""

    workspace_path = prepare_workspace(request.instance.repo, request.output_dir)
    pre_patch_log_path = request.output_dir / "pre_patch_test.log"
    build_log_path = request.output_dir / "build.log"
    test_log_path = request.output_dir / "test.log"
    patch_path = request.output_dir / "patch.diff"
    apply_log_path = request.output_dir / "apply_patch.log"

    pre_test_success, pre_test_output = run_commands(
        request.instance.test_cmds,
        workspace_path,
    )
    pre_patch_log_path.write_text(pre_test_output, encoding="utf-8")
    pre_status = parse_unittest_output(pre_test_output)

    apply_success = True
    apply_output = ""
    if request.instance.pred_patch:
        inline_patch_path = request.output_dir / "inline_pred_patch.diff"
        inline_patch_path.write_text(request.instance.pred_patch, encoding="utf-8")
        apply_success, apply_output = apply_patch(workspace_path, inline_patch_path)
        apply_log_path.write_text(apply_output, encoding="utf-8")

    build_success, build_output = (
        run_commands(request.instance.rebuild_cmds, workspace_path)
        if apply_success
        else (False, "")
    )
    test_success, test_output = (
        run_commands(request.instance.test_cmds, workspace_path)
        if apply_success
        else (False, "")
    )
    post_status = parse_unittest_output(test_output)
    (
        pass_to_pass_success,
        fail_to_pass_success,
        pass_to_pass_failure,
        fail_to_pass_failure,
    ) = compare_statuses(pre_status, post_status)

    patch_output = capture_git_diff(workspace_path) or request.instance.pred_patch
    build_log_path.write_text(build_output, encoding="utf-8")
    test_log_path.write_text(test_output, encoding="utf-8")
    patch_path.write_text(patch_output, encoding="utf-8")

    return CodeRunOutcome(
        resolved=build_success and test_success,
        pass_to_pass_success=pass_to_pass_success,
        pass_to_pass_failure=pass_to_pass_failure,
        fail_to_pass_success=fail_to_pass_success,
        fail_to_pass_failure=fail_to_pass_failure,
        logs={
            "workspace_path": str(workspace_path),
            "pre_patch_test_log_path": str(pre_patch_log_path),
            "apply_log_path": str(apply_log_path) if request.instance.pred_patch else "",
            "build_log_path": str(build_log_path),
            "test_log_path": str(test_log_path),
            "patch_path": str(patch_path),
        },
        details={
            "pre_test_success": pre_test_success,
            "post_test_success": test_success,
            "apply_success": apply_success,
            "pre_patch_status": pre_status,
            "post_patch_status": post_status,
        },
    )


_UNITTEST_RESULT = re.compile(r"^(test\w+.*)\s+\((.+)\)\s+\.\.\.\s+(ok|FAIL|ERROR|skipped.*)$")
# A test line whose status landed on a later line: output the test wrote to
# stderr (warnings, logging) follows the "... ", or a docstring line follows.
_UNITTEST_HEADER = re.compile(r"^(test\w+)\s+\(([^()\s]+)\)(?:\s+\.\.\.(?:\s.*)?)?$")
_UNITTEST_STATUS = re.compile(r"^(?:.*\s\.\.\.\s+)?(ok|FAIL|ERROR|skipped.*)$")


def parse_unittest_output(output: str) -> dict[str, str]:
    """Parse minimal unittest output into pass/fail/skip status per test case."""

    statuses: dict[str, str] = {}
    pending = ""
    for line in output.splitlines():
        stripped = line.strip()
        match = _UNITTEST_RESULT.match(stripped)
        if match:
            test_name, raw_status = f"{match.group(2)}::{match.group(1)}", match.group(3)
        else:
            header = _UNITTEST_HEADER.match(stripped)
            if header:
                pending = f"{header.group(2)}::{header.group(1)}"
                continue
            status = _UNITTEST_STATUS.match(stripped)
            if not (pending and status):
                continue
            test_name, raw_status = pending, status.group(1)
        pending = ""
        raw_status = raw_status.lower()
        if raw_status.startswith("ok"):
            statuses[test_name] = "pass"
        elif raw_status.startswith("skip"):
            statuses[test_name] = "skip"
        else:
            statuses[test_name] = "fail"
    return statuses


def compare_statuses(
    pre_status: dict[str, str],
    post_status: dict[str, str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Compute PASS_TO_PASS and FAIL_TO_PASS summaries."""

    all_tests = set(pre_status) | set(post_status)
    pass_to_pass_success: list[str] = []
    fail_to_pass_success: list[str] = []
    pass_to_pass_failure: list[str] = []
    fail_to_pass_failure: list[str] = []

    for test_name in sorted(all_tests):
        before = pre_status.get(test_name, "skip")
        after = post_status.get(test_name, "skip")
        if before == "pass":
            if after == "pass":
                pass_to_pass_success.append(test_name)
            else:
                pass_to_pass_failure.append(test_name)
        elif before == "fail":
            if after == "pass":
                fail_to_pass_success.append(test_name)
            else:
                fail_to_pass_failure.append(test_name)
    return (
        pass_to_pass_success,
        fail_to_pass_success,
        pass_to_pass_failure,
        fail_to_pass_failure,
    )
