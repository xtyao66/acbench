# Architecture

## High-Level Flow

The execution path is:

1. `acbench/orchestrator/cli.py` parses command-line inputs.
2. `acbench/orchestrator/validate.py` loads and normalizes the scenario.
3. `acbench/orchestrator/runner.py` selects the correct executor.
4. The executor runs code and/or ops work.
5. Result artifacts are written under `runs/`.

## Main Layers

- `acbench/orchestrator/`: flow control, CLI, readiness checks, demo/export helpers
- `tasks/`: scenario definitions and task assets
- `acbench/executors/`: live and dry-run execution paths
- `services/`: service docs and local fixture repositories
- `acbench/evaluation/`: batch scoring and report generation
- `acbench/agents/`: agent implementations
- `acbench/models/`: shared schemas for scenarios, runtime config, and results

## Layer Boundaries

- `orchestrator` decides what to run and in which order.
- `tasks` defines what the agent is being asked to do.
- `executors` decides how the work is performed.
- `services` provides the codebase, runtime, and fixture context.
- `evaluation` decides whether the run succeeded and how to summarize it.
- `agents` generates actions or patches, but does not own platform flow.
- `models` defines shared data shapes, but does not execute logic.

## Canonical Asset Locations

- `tasks/scenarios/`: benchmark definitions
- `services/catalog/`: service-level docs and metadata
- `services/fixtures/`: local fixture repositories and assets
- `patches/`: reference patches
- `manifests/`: batch scenario lists
- `predictions/`: batch evaluation inputs

## Current Benchmark Shape

Current scenario inventory:

- `3` code scenarios
- `3` ops-only scenarios
- `3` combined scenarios

Current service families:

- `billing_pricing`
- `feature_router`
- `maintenance_window`
- `cache_api`
- `queue_worker`
- `payments_api`

## Result Artifacts

Each run directory typically includes:

- `result.json`
- `summary.json`
- `diagnostics.json`

Code runs may also include:

- `openai_generated_patch.diff`
- `build.log`
- `test.log`
