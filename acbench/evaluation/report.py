"""Report generation helpers for the ACBench."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_markdown_report(evaluation_results: dict[str, Any]) -> str:
    """Render a compact markdown report from batch evaluation results."""

    lines: list[str] = []
    lines.append("# ACBench Evaluation Report")
    lines.append("")
    lines.append(f"- Manifest: `{evaluation_results.get('manifest', '')}`")
    lines.append(f"- Predictions: `{evaluation_results.get('predictions', '')}`")
    lines.append(f"- Submitted: `{evaluation_results.get('submitted', 0)}`")
    lines.append(f"- Success: `{evaluation_results.get('success', 0)}`")
    lines.append(f"- Failure: `{evaluation_results.get('failure', 0)}`")
    missing = evaluation_results.get("missing", [])
    lines.append(f"- Missing: `{len(missing)}`")
    lines.append("")
    lines.append("## Scenario Results")
    lines.append("")
    lines.append("| Scenario | Mode | Status | Build | Test | Detect | Localize | Repair | FAIL_TO_PASS | PASS_TO_PASS |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")

    for scenario_id, item in evaluation_results.get("results", {}).items():
        lines.append(
            "| "
            + f"{scenario_id} | "
            + f"{item.get('mode', '')} | "
            + f"{item.get('status', '')} | "
            + f"{item.get('build_success', False)} | "
            + f"{item.get('test_success', False)} | "
            + f"{item.get('detected', False)} | "
            + f"{item.get('localized', False)} | "
            + f"{item.get('repaired', False)} | "
            + f"{len(item.get('fail_to_pass_success', []))} | "
            + f"{len(item.get('pass_to_pass_success', []))} |"
        )

    lines.append("")
    lines.append("## Details")
    lines.append("")
    for scenario_id, item in evaluation_results.get("results", {}).items():
        lines.append(f"### `{scenario_id}`")
        lines.append("")
        lines.append(f"- Mode: `{item.get('mode', '')}`")
        lines.append(f"- Status: `{item.get('status', '')}`")
        lines.append(f"- Code Backend: `{item.get('code_backend', '')}`")
        lines.append(f"- Ops Backend: `{item.get('ops_backend', '')}`")
        lines.append(f"- Detected: `{item.get('detected', False)}`")
        lines.append(f"- Localized: `{item.get('localized', False)}`")
        lines.append(f"- Repaired: `{item.get('repaired', False)}`")
        lines.append(f"- Result Path: `{item.get('result_path', '')}`")
        lines.append(f"- Summary Path: `{item.get('summary_path', '')}`")
        lines.append(
            f"- FAIL_TO_PASS Success: `{len(item.get('fail_to_pass_success', []))}`"
        )
        lines.append(
            f"- PASS_TO_PASS Success: `{len(item.get('pass_to_pass_success', []))}`"
        )
        lines.append("")

    return "\n".join(lines) + "\n"


def render_run_markdown_report(
    result_payload: dict[str, Any],
    summary_payload: dict[str, Any],
    diagnostics_payload: dict[str, Any] | None = None,
) -> str:
    """Render a compact markdown report for one benchmark run bundle."""

    diagnostics_payload = diagnostics_payload or {}
    lines: list[str] = []
    lines.append("# ACBench Run Report")
    lines.append("")
    lines.append(f"- Scenario: `{result_payload.get('scenario_id', '')}`")
    lines.append(f"- Title: `{result_payload.get('title', '')}`")
    lines.append(f"- Mode: `{result_payload.get('mode', '')}`")
    lines.append(f"- Status: `{result_payload.get('status', '')}`")
    lines.append(f"- Started: `{result_payload.get('started_at', '')}`")
    lines.append(f"- Finished: `{result_payload.get('finished_at', '')}`")
    lines.append("")

    code = summary_payload.get("code")
    if code:
        lines.append("## Code")
        lines.append("")
        lines.append(f"- Backend: `{code.get('backend', '')}`")
        lines.append(f"- Success: `{code.get('success', False)}`")
        lines.append(f"- Build Success: `{code.get('build_success', False)}`")
        lines.append(f"- Test Success: `{code.get('test_success', False)}`")
        lines.append(f"- Submitted Instance: `{code.get('submitted_instance_id', '')}`")
        lines.append(f"- Resolved: `{code.get('resolved', False)}`")
        lines.append(f"- FAIL_TO_PASS Count: `{code.get('fail_to_pass_count', 0)}`")
        lines.append(f"- PASS_TO_PASS Count: `{code.get('pass_to_pass_count', 0)}`")
        lines.append(
            f"- FAIL_TO_PASS Failure Count: `{code.get('fail_to_pass_failure_count', 0)}`"
        )
        lines.append(
            f"- PASS_TO_PASS Failure Count: `{code.get('pass_to_pass_failure_count', 0)}`"
        )
        lines.append("")

    ops = summary_payload.get("ops")
    if ops:
        lines.append("## Ops")
        lines.append("")
        lines.append(f"- Backend: `{ops.get('backend', '')}`")
        lines.append(f"- Success: `{ops.get('success', False)}`")
        lines.append(f"- Detected: `{ops.get('detected', False)}`")
        lines.append(f"- Localized: `{ops.get('localized', False)}`")
        lines.append(f"- Repaired: `{ops.get('repaired', False)}`")
        lines.append("")

    artifacts = result_payload.get("artifacts", {})
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- Result Path: `{artifacts.get('result_path', '')}`")
    lines.append(f"- Summary Path: `{artifacts.get('summary_path', '')}`")
    lines.append(f"- Diagnostics Path: `{artifacts.get('diagnostics_path', '')}`")
    if artifacts.get("build_log_path"):
        lines.append(f"- Build Log Path: `{artifacts.get('build_log_path', '')}`")
    if artifacts.get("test_log_path"):
        lines.append(f"- Test Log Path: `{artifacts.get('test_log_path', '')}`")
    if artifacts.get("patch_path"):
        lines.append(f"- Patch Path: `{artifacts.get('patch_path', '')}`")
    lines.append("")

    notes = result_payload.get("notes", [])
    if notes:
        lines.append("## Notes")
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")

    if diagnostics_payload:
        lines.append("## Diagnostics")
        lines.append("")
        run_config = diagnostics_payload.get("run_config", {})
        readiness = diagnostics_payload.get("readiness", {})
        lines.append(f"- Dry Run: `{run_config.get('dry_run', '')}`")
        lines.append(f"- Max Steps: `{run_config.get('max_steps', '')}`")
        lines.append(f"- Ready For Live Run: `{readiness.get('ready_for_live_run', '')}`")
        lines.append("")

    return "\n".join(lines) + "\n"


def write_markdown_report(
    evaluation_results: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Write a markdown report for an evaluation bundle."""

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown_report(evaluation_results), encoding="utf-8")
    return target


def write_markdown_report_from_json(
    evaluation_json_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Load evaluation JSON and write a markdown report."""

    source = Path(evaluation_json_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    return write_markdown_report(payload, output_path)


def write_run_markdown_report(
    run_dir: str | Path,
    output_path: str | Path,
) -> Path:
    """Write a markdown report from one ACBench run directory."""

    base = Path(run_dir)
    result_payload = json.loads((base / "result.json").read_text(encoding="utf-8"))
    summary_payload = json.loads((base / "summary.json").read_text(encoding="utf-8"))
    diagnostics_path = base / "diagnostics.json"
    diagnostics_payload = (
        json.loads(diagnostics_path.read_text(encoding="utf-8"))
        if diagnostics_path.exists()
        else None
    )

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_run_markdown_report(
            result_payload=result_payload,
            summary_payload=summary_payload,
            diagnostics_payload=diagnostics_payload,
        ),
        encoding="utf-8",
    )
    return target
