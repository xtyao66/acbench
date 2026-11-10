# Experiment harness

These scripts ran the HPEC 2026 paper's experiments. Each one runs inside a GPU
job: it starts a vLLM or SGLang server for one model, waits for it to become
healthy, then drives ACBench against that local OpenAI-compatible endpoint and
writes CSV/JSONL results. The job definitions for the authors' GPU platform are
not included; to rerun, start a server for the model yourself and point the
scripts at it (see each script's docstring for its environment variables).

The paper's tables and figures are regenerated from the archived results in
[`paper/artifact/`](../paper/artifact/README.md), without rerunning anything.

| Script | Purpose |
| --- | --- |
| `run_perf_loop.py` | Feedback-scaffold study: a K-iteration optimization loop per scenario and feedback arm (RQ1/RQ2 data) |
| `perf_feedback.py`, `perf_profile.py` | Render the feedback each arm shows, from `go test -bench`, pprof and escape-analysis output |
| `measure_perf_go.py` | Measured-speedup grading for real Go optimization PRs |
| `validate_perf_gold.py` | Model-free check that a candidate scenario's gold fix applies, passes and speeds things up |
| `materialize_real.py`, `smoke_real.py` | Build the bug-present repositories for real-PR scenarios and grade their gold fixes |
| `run_perf_real.py`, `run_perf_sweep.py`, `measure_perf.py` | Measured-speedup sweeps with diagnosis conditions |
| `run_experiments.py` | Diagnosis-coupling study over combined scenarios |
| `run_acbench_eval.py` | Run ACBench manifests against a served model |
| `diag_patch_gen.py` | Capture raw model responses and extracted patches for debugging |

Changes to this harness after the paper's runs are listed in
[`CHANGELOG.md`](../CHANGELOG.md).
