# Contributing to ACBench

Thanks for your interest in improving ACBench. This guide covers how to set up a
development environment and how to contribute scenarios, agents, and tests.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the test suite:

```bash
python -m pytest
```

## Ways to contribute

### Add a scenario

1. Read `docs/SCENARIO_AUTHORING.md` and `docs/TASK_BANK_REQUIREMENTS.md`.
2. Add the scenario JSON under the appropriate directory:
   - `tasks/scenarios/local/{code,ops,combined}/`
   - `tasks/scenarios/github/{code,ops,combined}/`
3. Provide any fixture repository under `services/fixtures/` and a gold patch
   under `patches/` (for code/combined scenarios).
4. Validate it:

   ```bash
   acbench --scenario <path-to-scenario>.scenario.json --validate-scenario
   ```

5. Add the scenario to the relevant manifest under `manifests/` and, if it ships
   a gold prediction, to the matching file under `predictions/`.

### Add an agent

- Code agents must expose a patch-generation interface; ops agents must expose
  an analysis interface returning a structured, rubric-compatible assessment.
- See `acbench/agents/` for the built-in OpenAI, Azure OpenAI, Anthropic, and
  scripted agents as references.
- Custom agents can be wired in with `--code-agent-ref module:Class`,
  `--aiops-agent-ref module:Class`, or a profile under `configs/agents/`.

### Improve the runtime or docs

- Core runtime lives in `acbench/`. Keep changes covered by tests under
  `tests/`.
- User-facing documentation lives in `docs/` and `README.md`.

## Pull request checklist

- [ ] `python -m pytest` passes locally.
- [ ] New scenarios validate with `--validate-scenario`.
- [ ] New data files are placed under the data-licensed directories and noted in
      the relevant manifest/predictions files.
- [ ] Documentation is updated when behavior or interfaces change.

## Licensing of contributions

By contributing, you agree that your code contributions are licensed under the
[Apache License 2.0](LICENSE) and your data/scenario contributions under
[CC BY 4.0](LICENSE-DATA), consistent with the rest of the project.

Please also follow our [Code of Conduct](CODE_OF_CONDUCT.md).
