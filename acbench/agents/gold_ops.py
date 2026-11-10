"""Gold reference ops agent.

``GoldOpsAgent`` is the ops analog of a gold code patch: it emits the scenario's
expected diagnosis (the authored detection / localization / remediation
keywords) as a structured assessment. It is NOT a model — it reads the expected
answer — and exists to validate that the ops rubric grades a *correct* answer as
passing, and to provide a meaningful gold baseline for ops/combined scenarios
(instead of the synthetic auto-pass placeholder).

Because it surfaces the discriminative keywords in the sections the rubric grades
against, a gold run should clear the leakage-aware recall threshold on every
stage by construction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from acbench.executors.backends.ops.runtime import NativeOpsProblem


class GoldOpsAgent:
    """Reference ops agent that emits the expected, correct diagnosis."""

    def configure(self, **kwargs: Any) -> None:
        self.config = kwargs

    def analyze(self, problem: NativeOpsProblem, *, output_dir: Path) -> dict[str, Any]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        detection = ", ".join(problem.detection_keywords) or "incident detected"
        localization = ", ".join(problem.localization_keywords) or (problem.service or "service")
        remediation = ", ".join(problem.repair_keywords) or "apply the documented fix"

        assessment = {
            "detected": True,
            "localized": True,
            "repaired": True,
            "summary": f"Incident confirmed for {problem.service}: {detection}.",
            "root_cause": f"Root cause localized to {localization} ({detection}).",
            "remediation": f"Remediation: {remediation}.",
            "evidence": list(problem.error_logs) + list(problem.detection_keywords),
        }

        prompt_path = output_dir / "gold_ops_prompt.txt"
        response_path = output_dir / "gold_ops_response.txt"
        assessment_path = output_dir / "gold_ops_assessment.json"
        telemetry_path = output_dir / "gold_ops_telemetry.json"

        prompt_path.write_text(
            f"GOLD reference assessment for problem {problem.problem_id}", encoding="utf-8"
        )
        response_path.write_text(json.dumps(assessment, indent=2), encoding="utf-8")
        assessment_path.write_text(json.dumps(assessment, indent=2), encoding="utf-8")
        telemetry = {
            "answer_count": 1,
            "answer_durations_seconds": [0.0],
            "total_answer_seconds": 0.0,
            "average_answer_seconds": 0.0,
            "wall_time_seconds": 0.0,
            "answer_labels": ["gold_reference"],
        }
        telemetry_path.write_text(json.dumps(telemetry, indent=2), encoding="utf-8")

        return {
            "assessment": assessment,
            "prompt_path": str(prompt_path),
            "response_path": str(response_path),
            "assessment_path": str(assessment_path),
            "telemetry": telemetry,
            "telemetry_path": str(telemetry_path),
        }
