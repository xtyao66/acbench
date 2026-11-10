# Commands

All commands assume:

- you are in the repository root
- your virtual environment is activated

## Environment

```bash
acbench --doctor
acbench --write-readiness-report runs/readiness_report.json
```

## Scenario Validation

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --validate-scenario
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --check-readiness
```

## Single-Scenario Execution

Local code with a patch:

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --code-patch patches/billing_pricing_bundle_fix.diff
```

Local combined with a patch:

```bash
acbench --scenario tasks/scenarios/local/combined/billing_pricing__checkout_totals_incident.scenario.json --code-patch patches/billing_pricing_bundle_fix.diff
```

Local code with an OpenAI code agent:

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --code-agent-ref acbench.agents.openai_code:OpenAICodePatchAgent --openai-model gpt-4.1-mini --openai-api-key-env OPENAI_API_KEY
```

Local code with a Claude code agent:

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --code-agent-ref acbench.agents.anthropic_code:AnthropicCodePatchAgent --anthropic-model claude-sonnet-4-20250514 --anthropic-api-key-env ANTHROPIC_API_KEY
```

Local code through the generic agent profile entrypoint:

```bash
acbench --agent-config configs/agents/claude_sonnet.example.json --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json
```

Local combined with both OpenAI agents:

```bash
acbench --scenario tasks/scenarios/local/combined/billing_pricing__checkout_totals_incident.scenario.json --code-agent-ref acbench.agents.openai_code:OpenAICodePatchAgent --aiops-agent-ref acbench.agents.openai_ops:OpenAIOpsAgent --openai-model gpt-4.1-mini --openai-api-key-env OPENAI_API_KEY
```

Local combined with Claude code and ops agents:

```bash
acbench --scenario tasks/scenarios/local/combined/billing_pricing__checkout_totals_incident.scenario.json --code-agent-ref acbench.agents.anthropic_code:AnthropicCodePatchAgent --aiops-agent-ref acbench.agents.anthropic_ops:AnthropicOpsAgent --anthropic-model claude-sonnet-4-20250514 --anthropic-api-key-env ANTHROPIC_API_KEY
```

GitHub-derived code with an OpenAI code agent:

```bash
acbench --scenario tasks/scenarios/github/code/openclaw__pairing_state_array_persistence.scenario.json --code-agent-ref acbench.agents.openai_code:OpenAICodePatchAgent --openai-model gpt-4.1-mini --openai-api-key-env OPENAI_API_KEY
```

GitHub-derived combined with both OpenAI agents:

```bash
acbench --scenario tasks/scenarios/github/combined/openclaw__completion_process_leak_incident.scenario.json --code-agent-ref acbench.agents.openai_code:OpenAICodePatchAgent --aiops-agent-ref acbench.agents.openai_ops:OpenAIOpsAgent --openai-model gpt-4.1-mini --openai-api-key-env OPENAI_API_KEY
```

GitHub-derived combined with Claude code and ops agents:

```bash
acbench --scenario tasks/scenarios/github/combined/openclaw__completion_process_leak_incident.scenario.json --code-agent-ref acbench.agents.anthropic_code:AnthropicCodePatchAgent --aiops-agent-ref acbench.agents.anthropic_ops:AnthropicOpsAgent --anthropic-model claude-sonnet-4-20250514 --anthropic-api-key-env ANTHROPIC_API_KEY
```

Ops-only validation:

```bash
acbench --scenario tasks/scenarios/local/ops/cache_api__stale_index_alert.scenario.json --validate-scenario
```

Dry run:

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --dry-run
```

## Batch Evaluation

Full local gold suite:

```bash
acbench --manifest manifests/local_suite.json --predictions predictions/local_gold.json --evaluation-output runs/local_suite_eval.json
```

Full GitHub/OpenClaw gold suite:

```bash
acbench --manifest manifests/github_openclaw_extended.json --predictions predictions/github_openclaw_extended_gold.json --evaluation-output runs/github_openclaw_extended_gold_eval.json
```

## OpenAI Agent Batch Runs

Edit `configs/openai_direct.local.json`, then run:

```bash
python scripts/run_openai_agent_evals.py --config configs/openai_direct.local.json
```

## Anthropic Agent Batch Runs

Copy the example config, fill the key, then run:

```bash
cp configs/anthropic_direct.example.json configs/anthropic_direct.local.json
python scripts/run_anthropic_agent_evals.py --config configs/anthropic_direct.local.json
```

## Azure OpenAI Agent Batch Runs

Copy the example config, fill the Azure deployment name, resource base URL, and
API key, then run:

```bash
cp configs/azure_openai_direct.example.json configs/azure_openai_direct.local.json
python scripts/run_azure_openai_agent_evals.py --config configs/azure_openai_direct.local.json
```

## Generic Agent Batch Runs

Use one provider-agnostic agent profile:

```bash
python scripts/run_agent_evals.py --agent-config configs/agents/claude_sonnet.example.json
python scripts/run_agent_evals.py --agent-config configs/agents/openai_gpt41mini.example.json
python scripts/run_agent_evals.py --agent-config configs/agents/azure_openai.example.json
```

## Export

```bash
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --export-code-instance out/code_only_billing_pricing_bundle_threshold.instance.json
```

## Reports

From an evaluation JSON:

```bash
acbench --evaluation-json runs/local_suite_eval.json --write-markdown-report runs/local_suite_eval.md
```

From one run directory:

```bash
acbench --run-dir runs/code_only_billing_pricing_bundle_threshold-YYYYMMDD-HHMMSS-XXXXXX --write-run-markdown-report runs/code_only_billing_pricing_bundle_threshold_report.md
```

## Demo

```bash
acbench --run-local-demo demo_out
```
