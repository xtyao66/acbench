# ACBench: Agentic Cloud Benchmark

[![License: Apache-2.0](https://img.shields.io/badge/Code%20License-Apache%202.0-blue.svg)](LICENSE)
[![Data License: CC BY 4.0](https://img.shields.io/badge/Data%20License-CC%20BY%204.0-lightgrey.svg)](LICENSE-DATA)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

ACBench is a **reproducible benchmark for evaluating whether AI agents can handle
realistic cloud engineering work.** It measures three capabilities that recur in
day-to-day cloud operations and maintenance:

- **Code repair** — fix bugs in local repository fixtures and pass tests.
- **Ops incident analysis** — diagnose incident-style failures from logs,
  symptoms, reproduction steps, and service context, graded against explicit
  rubrics.
- **Combined workflows** — reason through an incident and then repair the code
  that caused it.

Scenarios are defined as JSON files, code tasks run against pinned local fixture
repositories, ops tasks are graded with explicit rubrics, and batch evaluations
write structured output under `runs/`. Every scenario pins its source and
execution path so evaluations avoid branch drift and hidden remote-state
changes.

## Citation

If you use ACBench in your research, please cite:

```bibtex
@misc{acbench2026,
  title  = {ACBench: Agentic Cloud Benchmark},
  author = {ACBench Team},
  year   = {2026},
  note   = {A reproducible benchmark for code repair, ops incident analysis,
            and combined cloud agent workflows},
  url    = {https://github.com/xtyao66/acbench}
}
```

See [`CITATION.cff`](CITATION.cff) for machine-readable citation metadata.

## Scope

The benchmark currently contains **61 scenarios**:

| Source | Code | Ops | Combined | Total |
| --- | ---: | ---: | ---: | ---: |
| Local fixtures | 3 | 6 | 3 | 12 |
| GitHub-derived OpenClaw fixtures | 15 | 19 | 15 | 49 |
| **Total** | **18** | **25** | **18** | **61** |

Scenario locations:

- local scenarios: `tasks/scenarios/local/{code,ops,combined}/`
- GitHub-derived scenarios: `tasks/scenarios/github/{code,ops,combined}/`

The GitHub-derived task bank is built from localized reproductions and
OpenClaw-style synthetic incidents. These are not live checkouts of any upstream
repository; they are stable local fixtures and rubrics derived from real issue
patterns, so results are reproducible and independent of moving branches.

## Supported Agent Types

ACBench has built-in integrations for live model providers:

- OpenAI
- Azure OpenAI
- Anthropic / Claude

Built-in live agent classes:

- `acbench.agents.openai_code:OpenAICodePatchAgent`
- `acbench.agents.openai_ops:OpenAIOpsAgent`
- `acbench.agents.azure_openai_code:AzureOpenAICodePatchAgent`
- `acbench.agents.azure_openai_ops:AzureOpenAIOpsAgent`
- `acbench.agents.anthropic_code:AnthropicCodePatchAgent`
- `acbench.agents.anthropic_ops:AnthropicOpsAgent`

You can also plug in custom agents with:

- `--code-agent-ref module:Class`
- `--aiops-agent-ref module:Class`
- `--agent-config configs/agents/<profile>.json`

Code agents must expose a patch-generation interface. Ops agents must expose an
analysis interface that returns a structured assessment or rubric-compatible
answer.

## Repository Layout

- `acbench/`: core runtime package
- `acbench/orchestrator/`: CLI, runner, scenario validation, readiness checks
- `acbench/agents/`: OpenAI, Anthropic, scripted, and profile-based agents
- `acbench/executors/`: code and ops execution paths
- `acbench/evaluation/`: manifest evaluation and report helpers
- `acbench/models/`: scenario, runtime, and result schemas
- `tasks/`: scenario definitions and task-bank overview
- `services/`: service docs and local fixture repositories
- `patches/`: gold/reference patches
- `predictions/`: batch evaluation inputs
- `manifests/`: scenario bundles
- `runs/`: generated run outputs (git-ignored)
- `configs/`: example provider and agent-profile configs
- `docs/`: deeper documentation
- `paper/artifact/`: reproducibility artifact for the HPEC 2026 paper
- `website/`: static project website
- `tests/`: unit and integration tests

## Installation

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

To use the Anthropic / Claude agents, also install the optional extra:

```bash
python -m pip install -e ".[anthropic]"
```

After installation, check that the CLI is available:

```bash
acbench --doctor
```

## First Things To Try

Validate one scenario without executing it:

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --validate-scenario
```

Run a dry run:

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --dry-run
```

Run a local code-repair scenario with the gold patch:

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --code-patch patches/billing_pricing_bundle_fix.diff
```

This applies the reference patch to the local fixture repository and evaluates
whether the scenario passes its build/test criteria.

## Running With OpenAI Agents

Set your API key:

```bash
export OPENAI_API_KEY="<your-key>"
```

Run one local code scenario:

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --code-agent-ref acbench.agents.openai_code:OpenAICodePatchAgent --openai-model gpt-4.1-mini --openai-api-key-env OPENAI_API_KEY
```

Run one local combined scenario:

```bash
acbench --scenario tasks/scenarios/local/combined/billing_pricing__checkout_totals_incident.scenario.json --code-agent-ref acbench.agents.openai_code:OpenAICodePatchAgent --aiops-agent-ref acbench.agents.openai_ops:OpenAIOpsAgent --openai-model gpt-4.1-mini --openai-api-key-env OPENAI_API_KEY
```

Run one GitHub-derived combined scenario:

```bash
acbench --scenario tasks/scenarios/github/combined/openclaw__completion_process_leak_incident.scenario.json --code-agent-ref acbench.agents.openai_code:OpenAICodePatchAgent --aiops-agent-ref acbench.agents.openai_ops:OpenAIOpsAgent --openai-model gpt-4.1-mini --openai-api-key-env OPENAI_API_KEY
```

Run the default OpenAI batch config:

```bash
cp configs/openai_direct.example.json configs/openai_direct.local.json
python scripts/run_openai_agent_evals.py --config configs/openai_direct.local.json
```

## Running With Azure OpenAI Agents

Set your API key and copy the profile template:

```bash
export AZURE_OPENAI_API_KEY="<your-key>"
cp configs/agents/azure_openai.example.json configs/agents/azure_openai.local.json
```

Edit `configs/agents/azure_openai.local.json` so `model` is your Azure
deployment name and `base_url` is your resource URL, for example
`https://<resource>.openai.azure.com/openai/v1/`.

Run one scenario through the Azure profile:

```bash
acbench --agent-config configs/agents/azure_openai.local.json --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json
```

Run the default Azure batch config:

```bash
cp configs/azure_openai_direct.example.json configs/azure_openai_direct.local.json
python scripts/run_azure_openai_agent_evals.py --config configs/azure_openai_direct.local.json
```

## Running With Anthropic / Claude Agents

Set your API key:

```bash
export ANTHROPIC_API_KEY="<your-key>"
```

Run one local code scenario:

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --code-agent-ref acbench.agents.anthropic_code:AnthropicCodePatchAgent --anthropic-model claude-sonnet-4-20250514 --anthropic-api-key-env ANTHROPIC_API_KEY
```

Run one GitHub-derived combined scenario:

```bash
acbench --scenario tasks/scenarios/github/combined/openclaw__completion_process_leak_incident.scenario.json --code-agent-ref acbench.agents.anthropic_code:AnthropicCodePatchAgent --aiops-agent-ref acbench.agents.anthropic_ops:AnthropicOpsAgent --anthropic-model claude-sonnet-4-20250514 --anthropic-api-key-env ANTHROPIC_API_KEY
```

Run the default Anthropic batch config:

```bash
cp configs/anthropic_direct.example.json configs/anthropic_direct.local.json
python scripts/run_anthropic_agent_evals.py --config configs/anthropic_direct.local.json
```

Local config files such as `configs/*.local.json` are ignored by git.

## Running With Generic Agent Profiles

Agent profiles let you define code and ops providers in one JSON file.

Example profile files:

- `configs/agents/openai_gpt41mini.example.json`
- `configs/agents/claude_sonnet.example.json`
- `configs/agents/azure_openai.example.json`
- `configs/agents/volt_vllm.example.json` (self-hosted vLLM / OpenAI-compatible
  endpoint; see [`docs/DEPLOYMENT_VLLM.md`](docs/DEPLOYMENT_VLLM.md))

Run one scenario through a profile:

```bash
acbench --agent-config configs/agents/claude_sonnet.example.json --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json
```

Run the full local + GitHub suites through a profile:

```bash
python scripts/run_agent_evals.py --agent-config configs/agents/claude_sonnet.example.json
```

## Batch Evaluation

Run the full local gold suite:

```bash
acbench --manifest manifests/local_suite.json --predictions predictions/local_gold.json --evaluation-output runs/local_suite_eval.json
```

Run the full GitHub/OpenClaw gold suite:

```bash
acbench --manifest manifests/github_openclaw_extended.json --predictions predictions/github_openclaw_extended_gold.json --evaluation-output runs/github_openclaw_extended_gold_eval.json
```

Useful manifests:

- `manifests/local_code_suite.json`
- `manifests/local_ops_suite.json`
- `manifests/local_combined_suite.json`
- `manifests/local_suite.json`
- `manifests/github_openclaw_smoke.json`
- `manifests/github_openclaw_extended.json`

## Result Files

Each run creates a timestamped directory under `runs/`, or under the directory
named by the `ACBENCH_RUNS_DIR` environment variable when it is set.

The main files are:

- `result.json`: full structured result
- `summary.json`: compact summary
- `diagnostics.json`: run metadata and diagnostics

Code runs may also include:

- `openai_generated_patch.diff`
- `anthropic_generated_patch.diff`
- `agent_generated_patch.diff`
- `build.log`
- `test.log`

Ops runs may also include:

- `ops_eval/openai_ops_prompt.txt`
- `ops_eval/openai_ops_response.txt`
- `ops_eval/openai_ops_assessment.json`
- `ops_eval/anthropic_ops_prompt.txt`
- `ops_eval/anthropic_ops_response.txt`
- `ops_eval/anthropic_ops_assessment.json`

Batch evaluations can also write an aggregate JSON file through
`--evaluation-output`.

## Scenario Format

Every production scenario should define:

- `scenario_id`
- `title`
- `mode`
- `source`
- `service`
- `task`
- `visible_context`
- `build`
- `success_criteria`
- `evaluation`
- `constraints`
- `metadata`

Code-capable scenarios include `code_fault`. Ops-capable scenarios include
`ops_fault`.

For authoring rules, see:

- `docs/SCENARIO_AUTHORING.md`
- `docs/TASK_BANK_REQUIREMENTS.md`

## OpenClaw Task Bank

OpenClaw is the GitHub-derived service family used by ACBench. The scenarios are
localized reproductions and OpenClaw-style incidents based on real issue
patterns.

ACBench uses OpenClaw because the issue set is:

- concrete enough to reproduce
- realistic enough to avoid toy-only tasks
- clear enough to grade with tests or rubrics
- broad enough to support code, ops, and combined workflows

Current OpenClaw coverage:

- `15` code scenarios
- `19` ops scenarios
- `15` combined scenarios
- `49` total GitHub-derived scenarios

The canonical bundle is:

```text
manifests/github_openclaw_extended.json
```

## Reproducibility

ACBench is designed so that a result can be regenerated from a fixed input:

- Scenarios pin their source and execution path; GitHub-derived scenarios run on
  localized fixtures rather than live repository checkouts.
- Local ops scenarios are rubric-graded incident tasks with explicit criteria.
- Gold patches under `patches/` reproduce the reference solution for code tasks.
- Batch runs and aggregate evaluations are written as structured JSON under
  `runs/` and via `--evaluation-output`.
- API-backed agents require provider API keys in the configured environment
  variables; the scripted and gold-patch paths run with no external services.

## Project Website

A static project website is included under `website/`.

To view it locally from the repository root:

```bash
python3 -m http.server 8080 --directory website
```

Then open `http://localhost:8080`.

Website files:

- `website/index.html`: main page
- `website/styles.css`: page styling
- `website/main.js`: leaderboard rendering
- `website/assets/acbench-hero.png`: hero image

The site is static HTML/CSS/JS. A GitHub Actions workflow at
`.github/workflows/pages.yml` deploys `website/` to GitHub Pages on pushes to
`main`. Once Pages is enabled (Settings → Pages → Source: GitHub Actions), the
site is published at:

```text
https://xtyao66.github.io/acbench/
```

## Documentation

- `docs/QUICKSTART.md`
- `docs/COMMANDS.md`
- `docs/SCENARIO_AUTHORING.md`
- `docs/TASK_BANK_REQUIREMENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/DEPLOYMENT_VLLM.md` — run against a self-hosted vLLM / OpenAI-compatible endpoint
- `docs/INSPECT_AI.md` — run ACBench scenarios inside the inspect-ai harness
- `schemas/scenario.schema.json` — the portable scenario data contract (author third-party task packs against it)
- `tasks/README.md`
- `configs/agents/README.md`

## Contributing

Contributions are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to
add scenarios, agents, and tests, and [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
for community expectations.

## License

- **Code** is licensed under the [Apache License 2.0](LICENSE).
- **Benchmark data** (scenarios, fixtures, rubrics, gold patches under `tasks/`,
  `services/`, `patches/`, `predictions/`, `manifests/`) is licensed under
  [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE-DATA).
