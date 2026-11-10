# Running ACBench inside inspect-ai

ACBench ships as an [inspect-ai](https://inspect.aisi.org.uk/) task, so you can
run its incident-to-fix scenarios with inspect's model providers, logging, and
viewer — instead of (or in addition to) ACBench's own runner. **Grading reuses
ACBench's real executors and scorecard** (test-execution for code, the
leakage-aware rubric for ops), so inspect scores match the native runner.

This is the "distribution" path: meet users inside the harness they already run.

## Install

```bash
python -m pip install -e ".[inspect]"
```

## Run

From the ACBench repo root (scenarios reference repo-relative fixtures):

```bash
inspect eval acbench.integrations.inspect_ai:acbench_task \
    -T manifest=manifests/local_suite.json \
    --model openai/gpt-4.1-mini
```

- `-T manifest=...` selects any ACBench manifest (e.g. `manifests/combined_all.json`).
- `--model ...` is any inspect-supported provider (OpenAI, Anthropic, vLLM/local
  via `--model openai-api/<name>` with a base URL, etc.).
- Results open in the inspect viewer: `inspect view`.

## How it maps

| ACBench concept | inspect-ai |
| --- | --- |
| manifest of scenarios | `dataset` (one `Sample` per scenario) |
| build the patch/diagnosis prompt + call the model | `solver` (`acbench_solver`) |
| apply patch + run tests / grade the rubric | `scorer` (`acbench_scorer`) returning `final_score` |

- **code_only**: the model returns a unified diff; ACBench's `LocalCodeExecutor`
  applies it and grades ID-validated `FAIL_TO_PASS`/`PASS_TO_PASS`.
- **ops_only**: the model returns a JSON assessment; ACBench's leakage-aware
  rubric grades it.
- **combined**: genuinely two-step — the model diagnoses, then the diagnosis is
  threaded into the repair prompt (the same coupling as the native runner), and
  both stages are scored into one `final_score`.

The score `metadata` carries the full ACBench `score_breakdown` (per-stage
components, weights, coupling block, failure reasons).
