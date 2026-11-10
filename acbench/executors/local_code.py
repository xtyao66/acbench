"""Local command-based code executor for the ACBench."""

from __future__ import annotations

from pathlib import Path
import re
from time import perf_counter
from typing import Any

from acbench.agents.coupling import localization_consistent
from acbench.agents.loader import load_object
from acbench.executors.backends.code.runner import parse_unittest_output
from acbench.executors.backends.code.standalone import (
    apply_patch,
    capture_git_diff,
    prepare_workspace,
    run_commands,
    run_single_command,
)
from acbench.executors.base import BenchmarkExecutor
from acbench.models.result import ExecutorResult
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec
from acbench.paths import resolve_repo_path


def canonical_test_id(raw: str) -> str:
    """Normalize a test identifier so scenario IDs and parsed keys align.

    Maps ``module.Class::method`` (scenario form) and
    ``module.Class.method::method`` (parsed unittest key) to a single canonical
    ``module.Class.method`` form by unifying ``::`` to ``.`` and collapsing a
    duplicated trailing method. A pytest ``path/to/test_mod.py::Class::method``
    keeps its directories (``path.to.test_mod.Class.method``) so tests in
    different directories stay distinct; see ``_compare_statuses`` for matching.
    """

    text = str(raw).strip()
    head, sep, rest = text.partition("::")
    if sep and head.endswith(".py"):
        head = head.replace("\\", "/")[: -len(".py")].replace("/", ".")
        text = f"{head}::{rest}"
    text = text.replace("::", ".")
    parts = [part for part in text.split(".") if part]
    if len(parts) >= 2 and parts[-1] == parts[-2]:
        parts = parts[:-1]
    return ".".join(parts)


def patch_modified_paths(patch_text: str) -> list[str]:
    """Extract the repository-relative paths a unified diff modifies.

    Both sides of every file header are collected (``diff --git`` a/b paths,
    ``---`` / ``+++`` lines, ``rename``/``copy`` headers): patch appliers write
    to the old-side path and a rename removes it, so checking only the new side
    would let a patch edit a forbidden file under a harmless ``+++`` name.
    """

    lines = patch_text.splitlines()
    paths: list[str] = []
    for index, line in enumerate(lines):
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        targets: list[str] = []
        prefixed = True
        if line.startswith("diff --git "):
            targets = line.split()[2:4]
        elif line.startswith("--- ") and next_line.startswith("+++ "):
            targets = [line[4:], next_line[4:]]
        elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            targets = [line.split(" ", 2)[2]]
            prefixed = False
        for target in targets:
            # Drop a trailing tab-delimited timestamp some diffs include.
            target = target.split("\t", 1)[0].strip()
            if not target or target == "/dev/null":
                continue
            if prefixed and target.startswith(("a/", "b/")):
                target = target[2:]
            if target and target not in paths:
                paths.append(target)
    return paths


def _normalize_repo_path(path: str) -> str:
    """Normalize a repo-relative path so './tests/x', 'tests/../tests/x', and
    leading-slash variants all collapse to the same canonical form."""

    import posixpath

    text = str(path).replace("\\", "/").strip()
    if not text:
        return ""
    return posixpath.normpath(text).lstrip("/")


def forbidden_path_violations(modified: list[str], forbidden: list[str]) -> list[str]:
    """Return modified paths that fall under any forbidden path/prefix/glob.

    Paths are canonicalized first so an agent cannot evade the check with
    './tests/...', 'tests/../tests/...', '/tests/...', or backslash variants.
    Matching ignores case, because on a case-insensitive filesystem (Windows,
    macOS) 'Tests/x' is the same file as 'tests/x'. A path that climbs out of
    the repository ('../...') or names a drive is always a violation: it cannot
    be checked against repo-relative rules and may re-enter the repo elsewhere.
    """

    from fnmatch import fnmatchcase

    violations: list[str] = []
    for raw in modified:
        path = _normalize_repo_path(raw)
        if path == ".." or path.startswith("../") or re.match(r"^[A-Za-z]:", path):
            violations.append(raw)
            continue
        path = path.casefold()
        for rule in forbidden:
            rule_raw = str(rule).replace("\\", "/").strip().casefold()
            rule_norm = _normalize_repo_path(rule_raw)
            prefix = rule_norm.rstrip("/") + "/" if rule_norm else ""
            if (
                (rule_norm and path == rule_norm)
                or (prefix and path.startswith(prefix))
                or fnmatchcase(path, rule_raw)
                or (rule_norm and fnmatchcase(path, rule_norm))
            ):
                violations.append(raw)
                break
    return violations


class LocalCodeExecutor(BenchmarkExecutor):
    """Execute rebuild and test commands directly in a local repository."""

    def __init__(self) -> None:
        super().__init__(backend_name="acbench-local-code")

    def execute(
        self,
        scenario: ScenarioSpec,
        run_dir: Path,
        run_config: RunConfig,
    ) -> ExecutorResult:
        started = perf_counter()
        repo_path = resolve_repo_path(scenario.service.repository_path or "")
        workspace_path = prepare_workspace(repo_path, run_dir)
        language = self._resolve_language(scenario, workspace_path)

        pre_patch_log_path = run_dir / "pre_patch_test.log"
        build_log_path = run_dir / "build.log"
        test_log_path = run_dir / "test.log"
        patch_path = run_dir / "patch.diff"
        apply_log_path = run_dir / "apply_patch.log"
        # Per-command budget; a command that exceeds it is killed and fails.
        timeout = (
            scenario.constraints.max_runtime_minutes * 60
            if scenario.constraints.max_runtime_minutes > 0
            else None
        )

        pre_test_success, pre_test_output = self._run_commands(
            scenario.build.test_cmds,
            workspace_path,
            timeout,
        )
        pre_patch_log_path.write_text(pre_test_output, encoding="utf-8")
        pre_status = self._parse_test_output_for_language(pre_test_output, language)

        applied_patch = ""
        apply_success = True
        forbidden_violations: list[str] = []
        modified_paths: list[str] = []
        patch_file_path, agent_artifacts = self._resolve_patch_file(
            scenario=scenario,
            run_config=run_config,
            run_dir=run_dir,
        )
        if patch_file_path:
            patch_file = resolve_repo_path(patch_file_path)
            patch_text = patch_file.read_text(encoding="utf-8", errors="replace")
            modified_paths = patch_modified_paths(patch_text)
            forbidden_violations = forbidden_path_violations(
                modified_paths, scenario.evaluation.forbidden_paths
            )
            if forbidden_violations:
                # Patch edits oracle / forbidden files (e.g. the tests). Reject it
                # outright so an agent cannot earn credit by rewriting the oracle.
                apply_success = False
                applied_patch = (
                    "Patch rejected: modifies forbidden path(s): "
                    + ", ".join(forbidden_violations)
                    + "\n"
                )
                apply_log_path.write_text(applied_patch, encoding="utf-8")
            else:
                apply_success, applied_patch = self._apply_patch(workspace_path, patch_file)
                apply_log_path.write_text(applied_patch, encoding="utf-8")

        build_success, build_output = self._run_commands(
            scenario.build.rebuild_cmds,
            workspace_path,
            timeout,
        ) if apply_success else (False, "")
        test_success, test_output = self._run_commands(
            scenario.build.test_cmds,
            workspace_path,
            timeout,
        ) if apply_success else (False, "")
        post_status = self._parse_test_output_for_language(test_output, language)
        (
            pass_to_pass,
            fail_to_pass,
            pass_to_pass_failure,
            fail_to_pass_failure,
            id_validated,
        ) = self._compare_statuses(
            pre_status,
            post_status,
            scenario.evaluation.fail_to_pass,
            scenario.evaluation.pass_to_pass,
        )
        patch_output = self._capture_git_diff(workspace_path)
        if not patch_output and patch_file_path:
            # Non-git workspace: record the patch that was submitted instead.
            patch_output = resolve_repo_path(patch_file_path).read_text(
                encoding="utf-8", errors="replace"
            )

        build_log_path.write_text(build_output, encoding="utf-8")
        test_log_path.write_text(test_output, encoding="utf-8")
        patch_path.write_text(patch_output, encoding="utf-8")

        repaired = build_success and test_success
        success = True
        if scenario.success_criteria.require_build_success and not build_success:
            success = False
        if scenario.success_criteria.require_test_success and not test_success:
            success = False
        if scenario.success_criteria.require_repair and not repaired:
            success = False
        if forbidden_violations:
            success = False
        # When the scenario names oracle tests, gate success on those specific
        # IDs: every FAIL_TO_PASS must pass and no PASS_TO_PASS may regress.
        if id_validated and (fail_to_pass_failure or pass_to_pass_failure):
            success = False

        metrics: dict[str, Any] = {
            "rebuild_cmd_count": len(scenario.build.rebuild_cmds),
            "test_cmd_count": len(scenario.build.test_cmds),
            "pre_test_success": pre_test_success,
            "post_test_success": test_success,
            "pre_test_cases": len(pre_status),
            "post_test_cases": len(post_status),
            "executor_total_seconds": round(perf_counter() - started, 6),
        }
        details: dict[str, Any] = {
            "repository_path": str(repo_path),
            "workspace_path": str(workspace_path),
            "language": language,
            "max_steps": run_config.max_steps,
            "apply_success": apply_success,
            "code_patch_path": str(patch_file_path) if patch_file_path else "",
            "pre_patch_status": pre_status,
            "post_patch_status": post_status,
            "id_validated": id_validated,
            "modified_paths": modified_paths,
            "forbidden_paths": list(scenario.evaluation.forbidden_paths),
            "forbidden_paths_violation": bool(forbidden_violations),
            "forbidden_paths_violated": forbidden_violations,
            "ops_diagnosis_provided": bool(run_config.upstream_ops_diagnosis),
            "diagnosis_localization_consistent": localization_consistent(
                run_config.upstream_ops_diagnosis,
                modified_paths,
                scenario.ops_fault.localization_keywords if scenario.ops_fault else [],
            ),
        }
        logs = {
            "apply_log_path": str(apply_log_path) if patch_file_path else "",
            "pre_patch_test_log_path": str(pre_patch_log_path),
            "build_log_path": str(build_log_path),
            "test_log_path": str(test_log_path),
            "patch_path": str(patch_path),
        }
        telemetry = agent_artifacts.get("telemetry", {})
        if isinstance(telemetry, dict) and telemetry:
            metrics.update(
                {
                    "agent_answer_count": int(telemetry.get("answer_count", 0)),
                    "agent_answer_durations_seconds": list(
                        telemetry.get("answer_durations_seconds", [])
                    ),
                    "agent_total_answer_seconds": float(
                        telemetry.get("total_answer_seconds", 0.0)
                    ),
                    "agent_average_answer_seconds": float(
                        telemetry.get("average_answer_seconds", 0.0)
                    ),
                    "agent_wall_time_seconds": float(
                        telemetry.get("wall_time_seconds", 0.0)
                    ),
                }
            )
            details["agent_telemetry"] = telemetry
        telemetry_path = agent_artifacts.get("telemetry_path", "")
        if telemetry_path:
            logs["agent_telemetry_path"] = str(telemetry_path)
        prompt_path = agent_artifacts.get("prompt_path", "")
        response_path = agent_artifacts.get("response_path", "")
        if prompt_path:
            logs["agent_prompt_path"] = str(prompt_path)
        if response_path:
            logs["agent_response_path"] = str(response_path)

        return ExecutorResult(
            backend=self.backend_name,
            success=success,
            repaired=repaired,
            build_success=build_success,
            test_success=test_success,
            pass_to_pass_success=pass_to_pass,
            pass_to_pass_failure=pass_to_pass_failure,
            fail_to_pass_success=fail_to_pass,
            fail_to_pass_failure=fail_to_pass_failure,
            metrics=metrics,
            logs=logs,
            details=details,
        )

    @staticmethod
    def _resolve_patch_file(
        scenario: ScenarioSpec,
        run_config: RunConfig,
        run_dir: Path,
    ) -> tuple[Path | None, dict[str, Any]]:
        if run_config.code_patch_path:
            return Path(run_config.code_patch_path), {}
        if not run_config.code_agent_ref:
            return None, {}

        agent_cls = load_object(run_config.code_agent_ref)
        agent = agent_cls()
        if not hasattr(agent, "generate_patch"):
            raise ValueError(
                f"Configured code agent `{run_config.code_agent_ref}` does not expose `generate_patch`."
            )
        agent_artifacts = agent.generate_patch(
            scenario=scenario,
            run_config=run_config,
            output_dir=run_dir,
        )
        generated_patch_path = agent_artifacts.get("generated_patch_path", "")
        if generated_patch_path:
            return Path(generated_patch_path), agent_artifacts
        patch_text = agent_artifacts.get("patch_text", "")
        if not patch_text:
            return None, agent_artifacts
        patch_path = run_dir / "agent_generated_patch.diff"
        patch_path.write_text(patch_text, encoding="utf-8")
        return patch_path, agent_artifacts

    @staticmethod
    def _resolve_language(scenario: ScenarioSpec, workspace_path: Path) -> str:
        """Resolve the code-stage execution language.

        Honors an explicit ``build.language`` first. When it is left at the
        default ("python") but the workspace is clearly a Go module (``go.mod``
        present), infer "go" so harvested Go repos run correctly even if a
        scenario author forgot to set the field. Any explicit non-default value
        is always respected (never overridden by inference).
        """

        declared = str(getattr(scenario.build, "language", "") or "").strip().lower()
        if declared and declared != "python":
            return declared
        if not declared or declared == "python":
            if (Path(workspace_path) / "go.mod").exists():
                return "go"
        return declared or "python"

    def _parse_test_output_for_language(
        self, output: str, language: str
    ) -> dict[str, str]:
        """Parse test output using the backend selected by ``language``.

        "go" routes through the ``go test -json`` parser; everything else uses
        the existing pytest/unittest parser, so the Python path is unchanged.
        """

        if language == "go":
            from acbench.executors.backends.go_test import parse_go_test_json

            return parse_go_test_json(output)
        return self._parse_test_output(output)

    def _run_commands(
        self,
        commands: list[str],
        repo_path: Path,
        timeout: float | None = None,
    ) -> tuple[bool, str]:
        """Run a list of commands and aggregate their output."""

        return run_commands(commands, repo_path, timeout=timeout)

    @staticmethod
    def _run_single_command(command: str, repo_path: Path):
        """Run one command in the local repository."""

        return run_single_command(command, repo_path)

    @staticmethod
    def _capture_git_diff(repo_path: Path) -> str:
        """Capture the local git diff if the repository is under git."""

        return capture_git_diff(repo_path)

    @staticmethod
    def _apply_patch(repo_path: Path, patch_file: Path) -> tuple[bool, str]:
        """Apply a unified diff patch to the local repository."""

        return apply_patch(repo_path, patch_file)

    @classmethod
    def _parse_test_output(cls, output: str) -> dict[str, str]:
        """Parse unittest and/or pytest verbose output into per-test statuses."""

        statuses = cls._parse_unittest_output(output)
        statuses.update(cls._parse_pytest_output(output))
        return statuses

    @staticmethod
    def _parse_unittest_output(output: str) -> dict[str, str]:
        """Parse minimal unittest results into pass/fail status per test case."""

        return parse_unittest_output(output)

    @staticmethod
    def _parse_pytest_output(output: str) -> dict[str, str]:
        """Parse pytest verbose output (``nodeid PASSED`` / ``PASSED nodeid``)."""

        statuses: dict[str, str] = {}
        for line in output.splitlines():
            stripped = line.strip()
            match = re.match(r"^(\S+::\S+)\s+(PASSED|FAILED|ERROR|SKIPPED)\b", stripped)
            if match:
                name, raw_status = match.group(1), match.group(2)
            else:
                alt = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED)\s+(\S+::\S+)", stripped)
                if not alt:
                    continue
                name, raw_status = alt.group(2), alt.group(1)
            raw_status = raw_status.lower()
            if raw_status == "passed":
                statuses[name] = "pass"
            elif raw_status == "skipped":
                statuses[name] = "skip"
            else:
                statuses[name] = "fail"
        return statuses

    @staticmethod
    def _compare_statuses(
        pre_status: dict[str, str],
        post_status: dict[str, str],
        fail_to_pass_ids: list[str] | None = None,
        pass_to_pass_ids: list[str] | None = None,
    ) -> tuple[list[str], list[str], list[str], list[str], bool]:
        """Compute PASS_TO_PASS / FAIL_TO_PASS summaries.

        When the scenario names oracle test IDs, validate against those specific
        IDs (the SWE-bench contract) rather than crediting arbitrary test
        transitions. Falls back to transition-based comparison only when no
        named IDs are provided.
        """

        fail_to_pass_ids = list(fail_to_pass_ids or [])
        pass_to_pass_ids = list(pass_to_pass_ids or [])

        if fail_to_pass_ids or pass_to_pass_ids:
            post_canonical = {canonical_test_id(k): v for k, v in post_status.items()}

            def passed(test_id: str) -> bool:
                wanted = canonical_test_id(test_id)
                if wanted in post_canonical:
                    return post_canonical[wanted] == "pass"
                # A scenario may name 'test_mod.Class.method' while pytest reports
                # 'tests/test_mod.py::Class::method': accept a match on a unique
                # suffix, and give no credit when the suffix is ambiguous.
                matches = [v for k, v in post_canonical.items() if k.endswith(f".{wanted}")]
                return len(matches) == 1 and matches[0] == "pass"

            fail_to_pass_success = [t for t in fail_to_pass_ids if passed(t)]
            fail_to_pass_failure = [t for t in fail_to_pass_ids if not passed(t)]
            pass_to_pass_success = [t for t in pass_to_pass_ids if passed(t)]
            pass_to_pass_failure = [t for t in pass_to_pass_ids if not passed(t)]
            return (
                pass_to_pass_success,
                fail_to_pass_success,
                pass_to_pass_failure,
                fail_to_pass_failure,
                True,
            )

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
            False,
        )
