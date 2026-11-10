# Scenario Authoring

All supported benchmark scenarios now live under [`tasks/scenarios/`](../tasks/scenarios).

For the scenario standard and curation bar, start with:

- [`docs/TASK_BANK_REQUIREMENTS.md`](../docs/TASK_BANK_REQUIREMENTS.md)

Current source directories:

- [`tasks/scenarios/local/`](../tasks/scenarios/local)
- [`tasks/scenarios/github/`](../tasks/scenarios/github)

## Start From Existing Files

Reference code scenarios:

- [`billing_pricing__bundle_discount_threshold.scenario.json`](../tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json)
- [`feature_router__denylist_precedence.scenario.json`](../tasks/scenarios/local/code/feature_router__denylist_precedence.scenario.json)
- [`maintenance_window__overnight_rollover.scenario.json`](../tasks/scenarios/local/code/maintenance_window__overnight_rollover.scenario.json)

Reference ops scenarios:

- [`cache_api__stale_index_alert.scenario.json`](../tasks/scenarios/local/ops/cache_api__stale_index_alert.scenario.json)
- [`queue_worker__backlog_spike.scenario.json`](../tasks/scenarios/local/ops/queue_worker__backlog_spike.scenario.json)
- [`payments_api__restart_loop_diagnosis.scenario.json`](../tasks/scenarios/local/ops/payments_api__restart_loop_diagnosis.scenario.json)

Reference combined scenario:

- [`billing_pricing__checkout_totals_incident.scenario.json`](../tasks/scenarios/local/combined/billing_pricing__checkout_totals_incident.scenario.json)
- [`feature_router__rollout_guard_incident.scenario.json`](../tasks/scenarios/local/combined/feature_router__rollout_guard_incident.scenario.json)
- [`maintenance_window__midnight_skip_incident.scenario.json`](../tasks/scenarios/local/combined/maintenance_window__midnight_skip_incident.scenario.json)

Reference GitHub-backed smoke scenarios:

- `tasks/scenarios/github/code/openclaw__pairing_state_array_persistence.scenario.json`
- `tasks/scenarios/github/ops/openclaw__docker_healthcheck_false_unhealthy.scenario.json`
- `tasks/scenarios/github/combined/openclaw__completion_process_leak_incident.scenario.json`

## Scenario V1 Blocks

Core fields for new scenarios:

- `scenario_id`
- `title`
- `mode`
- `source`
- `service`
- `task`
- `visible_context`
- `environment`
- `code_fault`
- `ops_fault`
- `build.rebuild_cmds`
- `build.test_cmds`
- `success_criteria`
- `evaluation`
- `constraints`
- `metadata`
- `metrics`
- `gold_patch_path`

Current local scenarios generally point at a fixture repository through:

- `service.repository_path`

Future GitHub-backed scenarios should instead pin:

- `source.repo_url`
- `source.base_commit`

The current GitHub smoke scenarios still include `service.repository_path` because they
run against localized reproductions of the upstream issue.

## Authoring Rules

- Put local code-only tasks under `tasks/scenarios/local/code/`.
- Put local ops-only tasks under `tasks/scenarios/local/ops/`.
- Put local combined tasks under `tasks/scenarios/local/combined/`.
- Put GitHub-backed tasks under `tasks/scenarios/github/<mode>/`.
- Keep scenario filenames stable and descriptive.
- Prefer one service family per scenario.
- Prefer one primary failure chain per scenario.
- Keep build and test commands directly runnable from the copied workspace.
- Do not leak the exact fix in `task.instructions` or `visible_context`.

## Validation

Validate every new scenario before running it:

```powershell
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --validate-scenario
```

Check whether the environment is ready:

```powershell
acbench --scenario tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json --check-readiness
```
