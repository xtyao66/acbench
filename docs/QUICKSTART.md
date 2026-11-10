# Quickstart

This guide is for someone using the repo for the first time.

## What You Can Do Here

With the current repo, you can:

- validate scenarios
- run local gold evaluations
- run GitHub-derived gold evaluations
- run local and GitHub scenarios with real OpenAI-backed agents
- run local and GitHub scenarios with real Claude-backed agents

Current scope:

- `9` local scenarios
- `45` GitHub-derived scenarios
- `54` scenarios total

## Setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

Check that the CLI is available:

```bash
acbench --doctor
```

## First Safe Command

Validate one scenario without running it:

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --validate-scenario
```

## First Gold Run

Run the full local gold suite:

```bash
acbench --manifest manifests/local_suite.json --predictions predictions/local_gold.json --evaluation-output runs/local_suite_eval.json
```

Run the GitHub/OpenClaw gold suite:

```bash
acbench --manifest manifests/github_openclaw_extended.json --predictions predictions/github_openclaw_extended_gold.json --evaluation-output runs/github_openclaw_extended_gold_eval.json
```

## First Manual Runs

Local code scenario with a gold patch:

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --code-patch patches/billing_pricing_bundle_fix.diff
```

Local code scenario with an OpenAI code agent:

```bash
export OPENAI_API_KEY="<your-key>"
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --code-agent-ref acbench.agents.openai_code:OpenAICodePatchAgent --openai-model gpt-4.1-mini --openai-api-key-env OPENAI_API_KEY
```

Local code scenario with a Claude code agent:

```bash
export ANTHROPIC_API_KEY="<your-key>"
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --code-agent-ref acbench.agents.anthropic_code:AnthropicCodePatchAgent --anthropic-model claude-sonnet-4-20250514 --anthropic-api-key-env ANTHROPIC_API_KEY
```

The same run through the generic agent profile entrypoint:

```bash
acbench --agent-config configs/agents/claude_sonnet.example.json --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json
```

Local combined scenario with both agents:

```bash
acbench --scenario tasks/scenarios/local/combined/billing_pricing__checkout_totals_incident.scenario.json --code-agent-ref acbench.agents.openai_code:OpenAICodePatchAgent --aiops-agent-ref acbench.agents.openai_ops:OpenAIOpsAgent --openai-model gpt-4.1-mini --openai-api-key-env OPENAI_API_KEY
```

GitHub-derived combined scenario with both agents:

```bash
acbench --scenario tasks/scenarios/github/combined/openclaw__completion_process_leak_incident.scenario.json --code-agent-ref acbench.agents.openai_code:OpenAICodePatchAgent --aiops-agent-ref acbench.agents.openai_ops:OpenAIOpsAgent --openai-model gpt-4.1-mini --openai-api-key-env OPENAI_API_KEY
```

GitHub-derived combined scenario with Claude code and ops agents:

```bash
acbench --scenario tasks/scenarios/github/combined/openclaw__completion_process_leak_incident.scenario.json --code-agent-ref acbench.agents.anthropic_code:AnthropicCodePatchAgent --aiops-agent-ref acbench.agents.anthropic_ops:AnthropicOpsAgent --anthropic-model claude-sonnet-4-20250514 --anthropic-api-key-env ANTHROPIC_API_KEY
```

## Batch Agent Run

Edit `configs/openai_direct.local.json`, then run:

```bash
python scripts/run_openai_agent_evals.py --config configs/openai_direct.local.json
```

For Claude, start from the example config and run:

```bash
cp configs/anthropic_direct.example.json configs/anthropic_direct.local.json
python scripts/run_anthropic_agent_evals.py --config configs/anthropic_direct.local.json
```

Or use the provider-agnostic batch runner:

```bash
python scripts/run_agent_evals.py --agent-config configs/agents/claude_sonnet.example.json
```

That default config currently runs:

- the full local suite
- the GitHub/OpenClaw extended suite

## Where Results Go

Each run writes a timestamped directory under `runs/`.

The most important files are:

- `result.json`
- `summary.json`
- `diagnostics.json`

Code runs may also write:

- `openai_generated_patch.diff`
- `anthropic_generated_patch.diff`
- `build.log`
- `test.log`

Ops runs may also write:

- `ops_eval/openai_ops_prompt.txt`
- `ops_eval/openai_ops_response.txt`
- `ops_eval/openai_ops_assessment.json`
- `ops_eval/anthropic_ops_prompt.txt`
- `ops_eval/anthropic_ops_response.txt`
- `ops_eval/anthropic_ops_assessment.json`

## Read Next

- `README.md`
- `docs/COMMANDS.md`
- `docs/SCENARIO_AUTHORING.md`
- `docs/TASK_BANK_REQUIREMENTS.md`
- `docs/ARCHITECTURE.md`
