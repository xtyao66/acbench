# ACBench Perf-Feedback Reproducibility Artifact

This folder is a runnable analysis snapshot for the HPEC 2026 paper. It contains the
retained scenario manifests, human fix patches, raw fleet registry/results, and
the scripts used for the paper's headline numbers.

It is not a turnkey rerun package for GB200 model serving and does not include
rendered serving prompts or profile payloads for independent prompt replay. The
snapshot is meant to regenerate and audit the reported tables, figures, and
overlap checks. The paper repository also keeps the source scenarios under
`tasks/scenarios/perf/`; this artifact copy is self-contained for the analyses
below. `ARTIFACT_MANIFEST.md` maps paper tables and figures to the files that
regenerate them.

## Contents

- `validated14.txt` lists the exact 14 scenario manifests used in the paper.
- `scenarios/` contains scenario JSON files; the validated subset is listed in
  `validated14.txt`.
- `patches/` contains the human optimization diffs used by the contamination
  probe.
- `volt-artifacts-fleet/` contains `JOB_REGISTRY.txt` and retrieved CSV/JSONL
  outputs used by the analyzers. Historical or in-flight notes in the registry
  are provenance; the analyzer outputs and this manifest define submission inputs.
- `results/gold_validation.json` is a partial 16-record validation output (eight
  retained and eight excluded); it is not a complete screening denominator.
- `manifests/perf_glm_gap.json`, `manifests/perf_mm_gapA.json`, and
  `manifests/perf_mm_gapB.json` preserve the small gap-run manifests used to
  complete larger-model OFF-fidelity coverage.
- `perf_score.py` implements the bounded log-speedup metric. The paper analyzers
  recompute scores from fixed manifest gold and ignore archived score columns.
- `diagrams/fig_scaffold.drawio` is the editable source for Figure 1. The
  repository's publication PDF is exported from this source.
- `analyze_fleet.py` reports per-cell coverage, F1 apply lift, F2 funnel shares,
  and descriptive fidelity means.
- `analyze_retryonly.py` reports the matched retry-only control for F1.
- `retry_sensitivity.py` intersects NR, GR, and ER on the exact candidate slots,
  then reports scenario-balanced apply and terminal outcomes across speedup
  thresholds.
- `fid_rigor.py` reports scenario-cluster F3 contrasts on both the available-pair
  and common seven-policy panels.
- `robustness_audit.py` reports complete-seed, task-exclusion, outlier, and
  score-threshold sensitivity checks.
- `analyze_contamination.py` reports changed-line overlap against human diffs.
- `make_panel_figures.py` regenerates the data-driven analysis figures used by
  the manuscript. Figure 1 is exported from its Draw.io source.

## Commands

Requires Python 3.10+. The analysis scripts use only the Python standard
library; figure regeneration additionally needs `matplotlib`
(`python3 -m pip install -r requirements.txt`).

Run from this directory:

```bash
python3 analyze_fleet.py
python3 analyze_retryonly.py
python3 retry_sensitivity.py
python3 fid_rigor.py
python3 robustness_audit.py
python3 analyze_contamination.py
python3 make_panel_figures.py
```

The figure command writes `results/figs/fig_apply_lift.{png,pdf}`,
`results/figs/fig_funnel.{png,pdf}`,
`results/figs/fig_retry_shift.{png,pdf}`, and
`results/figs/fig_fidelity.{png,pdf}` under this artifact folder.
Other Draw.io workflow sources are retained as legacy editable assets; they are
not embedded in the current manuscript.

Do not include interpreter caches such as `__pycache__/` in a release snapshot.
Older paper drafts, backup figures, local logs, and exploratory plots outside
this directory are not analysis inputs.
