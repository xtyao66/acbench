"""Demo helpers for the ACBench."""

from __future__ import annotations

from pathlib import Path

from acbench.evaluation.evaluate import evaluate_predictions
from acbench.evaluation.report import write_markdown_report
from acbench.paths import resolve_repo_path


def run_local_demo(output_dir: str | Path) -> dict:
    """Run the local gold suite and produce JSON and markdown outputs."""

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "local_suite_eval.json"
    md_path = target_dir / "local_suite_report.md"

    results = evaluate_predictions(
        manifest_path=resolve_repo_path("manifests/local_suite.json"),
        predictions_path=resolve_repo_path("predictions/local_gold.json"),
        output_path=json_path,
    )
    write_markdown_report(results, md_path)
    return {
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "results": results,
    }
