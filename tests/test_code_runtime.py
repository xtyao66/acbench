"""Tests for the internal standalone code runtime models."""

from __future__ import annotations

from pathlib import Path
import unittest

from acbench.executors.backends.code.runtime import (
    CodeRunOutcome,
    NativeCodeInstance,
    workspace_dir,
)


class CodeRuntimeTests(unittest.TestCase):
    def test_native_code_instance_round_trip_preserves_fields(self) -> None:
        payload = {
            "instance_id": "native-1",
            "repo": "owner/repo",
            "platform": "linux",
            "patch": "p",
            "pred_patch": "pp",
            "test_patch": "tp",
            "rebuild_cmds": ["cargo build"],
            "test_cmds": ["cargo test"],
            "print_cmds": ["git status"],
            "PASS_TO_PASS": ["t1"],
            "FAIL_TO_PASS": ["t2"],
            "docker_image": "example/native:latest",
            "log_parser": "none",
            "base_commit": "abc123",
        }

        instance = NativeCodeInstance.from_payload(payload)

        self.assertEqual(instance.instance_id, "native-1")
        self.assertEqual(instance.platform, "linux")
        self.assertEqual(instance.pass_to_pass, ["t1"])
        self.assertEqual(instance.fail_to_pass, ["t2"])
        self.assertEqual(instance.to_payload()["docker_image"], "example/native:latest")

    def test_code_run_outcome_to_report_uses_swe_style_shape(self) -> None:
        outcome = CodeRunOutcome(
            resolved=True,
            pass_to_pass_success=["t1"],
            fail_to_pass_success=["t2"],
            logs={"build_log": "build.log"},
            details={"note": "ok"},
        )

        report = outcome.to_report("native-1")

        self.assertEqual(report["instance_id"], "native-1")
        self.assertTrue(report["resolved"])
        self.assertEqual(report["PASS_TO_PASS"]["success"], ["t1"])
        self.assertEqual(report["FAIL_TO_PASS"]["success"], ["t2"])
        self.assertEqual(report["logs"]["build_log"], "build.log")

    def test_workspace_dir_is_stable(self) -> None:
        path = workspace_dir(Path("out"), "native-1")
        self.assertEqual(path, Path("out") / "native-1" / "workspace")


if __name__ == "__main__":
    unittest.main()
