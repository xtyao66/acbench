# Running ACBench against a self-hosted vLLM endpoint

ACBench can evaluate any model exposed through an **OpenAI-compatible** HTTP API,
including a model you serve yourself with [vLLM](https://github.com/vllm-project/vllm)
on your own GPUs (for example a GB200 rack on an internal platform). Nothing in
ACBench is tied to the hosted OpenAI service — the built-in OpenAI agents simply
point the OpenAI SDK at a custom `base_url`.

## 1. Serve the model with vLLM

Start vLLM's OpenAI-compatible server, e.g.:

```bash
vllm serve <model> \
  --served-model-name my-model \
  --tensor-parallel-size 8 \
  --host 0.0.0.0 --port 8000
```

This exposes `http://<host>:8000/v1` with `/v1/chat/completions` and
`/v1/models`. (On a managed GPU platform, submit this as an inference job and use
the service URL the platform assigns.)

> **Important:** vLLM implements the **chat-completions** API, not the newer
> Responses API. You must therefore set `"api": "chat_completions"` in the agent
> config (the example profile below already does). The default mode is
> `responses`, which a vLLM endpoint does not serve.

vLLM accepts any value for the API key unless you launched it with
`--api-key`. Export whatever it expects:

```bash
export OPENAI_API_KEY="dummy-key-or-your-configured-key"
```

## 2. Point ACBench at it

Copy and edit the example profile:

```bash
cp configs/agents/volt_vllm.example.json configs/agents/volt_vllm.local.json
# set base_url to your endpoint and model to your --served-model-name
```

`configs/agents/volt_vllm.example.json`:

```json
{
  "name": "volt-vllm-openai-compatible",
  "code": { "provider": "openai", "model": "<served-model-name>",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "http://<volt-inference-host>:8000/v1",
            "api": "chat_completions" },
  "ops":  { "provider": "openai", "model": "<served-model-name>",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "http://<volt-inference-host>:8000/v1",
            "api": "chat_completions" }
}
```

Run a single scenario:

```bash
acbench --agent-config configs/agents/volt_vllm.local.json \
  --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json
```

Or the full local + GitHub suites through the profile:

```bash
python scripts/run_agent_evals.py --agent-config configs/agents/volt_vllm.local.json
```

## 3. Notes

- The same `base_url` / `api: chat_completions` settings work via the CLI flags
  `--openai-base-url` and an `ops_agent_config`/`code_agent_config` `api` field.
- Ops scenarios are graded by the leakage-aware rubric and code scenarios by
  ID-validated tests — no provider-specific grading is involved, so results are
  comparable across hosted and self-hosted models.
- For combined scenarios the ops diagnosis is fed into the code stage
  automatically (see the `coupling` block in each scorecard).
