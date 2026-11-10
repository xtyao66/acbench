# Artifact Manifest

This directory is the runnable analysis snapshot for the HPEC 2026 paper. It
regenerates the paper's tables, figures, and audit outputs from retrieved rows;
it is not a turnkey package for rerunning GB200 model serving or replaying the
original rendered prompts/profile payloads. It is intended to be archived without
local caches, old drafts, or backup figures.

## Required Inputs

- `validated14.txt` and `scenarios/`: retained scenario set and benchmark metadata.
- `patches/`: human optimization diffs for gold validation and contamination checks.
- `volt-artifacts-fleet/`: raw registry, CSV rows, and captured patch JSONL files.
- `results/gold_validation.json`: partial validation output for eight retained
  and eight excluded scenarios; not a complete screening ledger.
- `manifests/perf_{glm,mm}_gap*.json`: gap-run manifests used to complete
  larger-model OFF-fidelity coverage.
- `perf_score.py`: bounded log-speedup metric used for paper scores.

## Regenerable Outputs

- Retained-scenario table: `validated14.txt` plus `scenarios/`.
- Raw apply-rate summaries: `analyze_fleet.py`; legacy retry-only summaries:
  `analyze_retryonly.py`.
- Exact-slot matched NR/GR/ER apply rates, terminal outcomes, and threshold
  sensitivity, including the model-level ER--GR outcome decomposition:
  `retry_sensitivity.py` and `make_panel_figures.py`.
- Fixed-gold F3 common-panel contrasts: `fid_rigor.py`, `fid_data.py`, and
  `make_panel_figures.py`.
- Complete-seed, task-exclusion, outlier, and score-threshold checks:
  `robustness_audit.py`.
- Training-data contamination probe: `analyze_contamination.py`.
- Recorded raw F1 and fixed-gold F3 output: `fid_stats.md`.

The workflow, validation-funnel, and evidence-map diagrams are retained as
legacy supporting assets. The current paper uses the compact editable scaffold
in `diagrams/fig_scaffold.drawio`; its publication PDF is a direct Draw.io
export. The validation-funnel denominator is not reconstructible from this
snapshot.

## Excluded From Archive

- `__pycache__/`, `.DS_Store`, and other interpreter or OS caches.
- Old paper drafts, local backup scripts, backup figures, and run logs outside
  this artifact directory.
- Unreferenced exploratory figures; only the numbered paper figures listed
  under Regenerable Outputs are submission inputs.
- Hidden `.done` files under `volt-artifacts-fleet/` are zero-byte local run
  markers and are not required by any reproduction command.
