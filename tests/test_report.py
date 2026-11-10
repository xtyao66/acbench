"""Tests for markdown reporting helpers."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from acbench.evaluation.report import (
    render_markdown_report,
    render_run_markdown_report,
    write_markdown_report_from_json,
    write_run_markdown_report,
)


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="acbench-report-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_render_markdown_report_contains_table(self) -> None:
        markdown = render_markdown_report(
            {
                "manifest": "m.json",
                "predictions": "p.json",
                "submitted": 1,
                "success": 1,
                "failure": 0,
                "missing": [],
                "results": {
                    "scenario-a": {
                        "mode": "ops_only",
                        "status": "success",
                        "build_success": True,
                        "test_success": True,
                        "detected": True,
                        "localized": True,
                        "repaired": True,
                        "fail_to_pass_success": ["t1"],
                        "pass_to_pass_success": ["t2"],
                        "code_backend": "acbench-local-code",
                        "ops_backend": "acbench-local-ops",
                        "result_path": "a/result.json",
                        "summary_path": "a/summary.json",
                    }
                },
            }
        )
        self.assertIn("| Scenario | Mode | Status | Build | Test | Detect | Localize | Repair | FAIL_TO_PASS | PASS_TO_PASS |", markdown)
        self.assertIn("scenario-a", markdown)

    def test_write_markdown_report_from_json(self) -> None:
        source = self.temp_dir / "eval.json"
        target = self.temp_dir / "report.md"
        source.write_text(
            json.dumps(
                {
                    "manifest": "m.json",
                    "predictions": "p.json",
                    "submitted": 0,
                    "success": 0,
                    "failure": 0,
                    "missing": [],
                    "results": {},
                }
            ),
            encoding="utf-8",
        )
        write_markdown_report_from_json(source, target)
        self.assertTrue(target.exists())

    def test_render_run_markdown_report_contains_key_fields(self) -> None:
        markdown = render_run_markdown_report(
            result_payload={
                "scenario_id": "scenario-a",
                "title": "Scenario A",
                "mode": "code_only",
                "status": "success",
                "started_at": "t1",
                "finished_at": "t2",
                "artifacts": {
                    "result_path": "a/result.json",
                    "summary_path": "a/summary.json",
                    "diagnostics_path": "a/diagnostics.json",
                },
                "notes": [],
            },
            summary_payload={
                "code": {
                    "backend": "swe-bench-live",
                    "success": True,
                    "build_success": True,
                    "test_success": True,
                    "submitted_instance_id": "instance-a",
                    "resolved": True,
                    "fail_to_pass_count": 1,
                    "pass_to_pass_count": 2,
                    "fail_to_pass_failure_count": 0,
                    "pass_to_pass_failure_count": 0,
                }
            },
            diagnostics_payload={
                "run_config": {"dry_run": False, "max_steps": 10},
                "readiness": {"ready_for_live_run": True},
            },
        )
        self.assertIn("# ACBench Run Report", markdown)
        self.assertIn("Submitted Instance", markdown)
        self.assertIn("instance-a", markdown)

    def test_write_run_markdown_report_from_run_dir(self) -> None:
        run_dir = self.temp_dir / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(
            json.dumps(
                {
                    "scenario_id": "scenario-a",
                    "title": "Scenario A",
                    "mode": "code_only",
                    "status": "success",
                    "started_at": "t1",
                    "finished_at": "t2",
                    "artifacts": {
                        "result_path": "a/result.json",
                        "summary_path": "a/summary.json",
                        "diagnostics_path": "a/diagnostics.json",
                    },
                    "notes": [],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "summary.json").write_text(
            json.dumps(
                {
                    "code": {
                        "backend": "swe-bench-live",
                        "success": True,
                        "build_success": True,
                        "test_success": True,
                        "submitted_instance_id": "instance-a",
                        "resolved": True,
                        "fail_to_pass_count": 1,
                        "pass_to_pass_count": 2,
                        "fail_to_pass_failure_count": 0,
                        "pass_to_pass_failure_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "diagnostics.json").write_text(
            json.dumps(
                {
                    "run_config": {"dry_run": False, "max_steps": 10},
                    "readiness": {"ready_for_live_run": True},
                }
            ),
            encoding="utf-8",
        )
        target = self.temp_dir / "run_report.md"
        write_run_markdown_report(run_dir, target)
        self.assertTrue(target.exists())
        self.assertIn("instance-a", target.read_text(encoding="utf-8"))
