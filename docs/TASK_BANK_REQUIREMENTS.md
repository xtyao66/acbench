# Task Bank Requirements

This file defines the minimum bar for scenarios that enter the ACBench task bank.

## What A Scenario Must Represent

Each scenario should be one reproducible engineering task with:

- a fixed target repository state
- a clear user-visible problem
- bounded agent-visible context
- explicit success criteria

## Required Blocks

Every production-quality scenario should include these blocks:

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

Code-capable scenarios must also include `code_fault`.
Ops-capable scenarios must also include `ops_fault`.

## Source Rules

- Always pin the repository version.
- For GitHub-backed tasks, set `source.type = "github"` and include `repo_url` plus `base_commit`.
- For local development fixtures, set `source.type = "local_fixture"` and use `service.repository_path`.
- Never rely on a moving branch such as `main` as the scenario definition.

## Authoring Rules

- Keep one primary failure chain per scenario.
- Do not leak the root cause or exact fix in `task.instructions`.
- Put only agent-visible evidence in `visible_context`.
- Keep grading behavioral whenever possible.
- Prefer allowing multiple valid fixes rather than matching one exact patch.

## Evaluation Rules

- Define whether build, test, repair, detection, and localization are required.
- Use `evaluation.fail_to_pass` for tests that should turn green.
- Use `evaluation.pass_to_pass` for tests that must stay green.
- Use `constraints.allow_test_changes = false` by default.

## Curation Checklist

Before a scenario is added to the task bank, confirm:

1. the scenario reproduces reliably
2. the scenario is pinned to a stable repo state
3. the agent-visible context is realistic and non-leaky
4. the success criteria are unambiguous
5. the scenario can be validated locally
6. the scenario measures a named capability, not just general difficulty

## Recommended First-Pass Metadata

- `metadata.difficulty`: `easy`, `medium`, `hard`, or `expert`
- `metadata.language`
- `metadata.framework`
- `metadata.categories`
- `metadata.source_benchmark`
