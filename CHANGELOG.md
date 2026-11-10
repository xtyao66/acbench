# Changelog

All notable changes to ACBench are recorded here. Versions follow
[Semantic Versioning](https://semver.org/); while the major version is 0, a minor
release may change how runs are scored.

## [Unreleased]

### Website

- The leaderboard of 0.1.0 results is removed. It returns when results exist
  under the 0.2.0 scoring.
- The page lists three built-in providers and six live agent classes, as the
  README does, restores two corrupted task-card icons, names the authors and
  adds a section on the performance-optimization track.

### Documentation

- The README, website and `CITATION.cff` cite the HPEC 2026 paper.
- The README and the task-bank overview list the scenario sets outside the
  61-scenario core suite.

## [0.2.0] - 2026-11-05

This release fixes defects found in a repository-wide review. Several of them
change scores, so **results from 0.2.0 are not comparable with results from
0.1.0**. Re-run any baseline you compare against.

### Scoring changes

- A stage with nothing gradeable (every rubric keyword already appears in the
  prompt) is now left out of the score instead of counting as 0 at full weight.
  Scorecards gain a `gradeable` field, `final_score` is `null` when nothing is
  gradeable, and evaluation averages skip such scenarios. This affects the
  ops-only scenarios `notifier__dead_letter_queue_overflow`,
  `openclaw__redis_session_eviction_storm` and `openclaw__worker_oom_killed_silent`.
- Ops runs no longer count an ungradeable required stage as detected,
  localized or repaired, and no longer report success with no gradeable signal.
- The ops leakage check now includes the `problem_id`, `application`, `service`
  and `deployment` fields, which agents are shown. Keywords equal to them no
  longer count as evidence; nine scenarios' localization sets shrink and two
  become ungradeable.
- A code run with no patch applied no longer earns build or pass-to-pass
  credit. Previously an empty answer scored 0.40, more than a wrong patch.
- Evaluation summaries average code and ops scores over the scenarios that ran
  that stage, keeping genuine zeros; previously zeros were dropped.

### Fixed: code execution

- Forbidden-path checks read both sides of a patch (`---`/`+++`, `diff --git`
  a/b paths, renames and copies), reject paths outside the workspace and compare
  case-insensitively. Previously a patch could edit the test oracle through its
  old-file path, a `../` path or a case variant and still score full marks.
- The non-git patch applier now handles plain multi-file diffs, timestamped
  headers, new files, deletions and renames, places each hunk at the match
  nearest its declared line, and preserves line endings and the final newline.
  It still accepts blank context lines and zero-context hunks as before.
- Passing unittest results are no longer lost when a test writes to stderr, and
  pytest-style test IDs now match scenario test names.
- Every build and test command has a timeout (`constraints.max_runtime_minutes`,
  default 30 minutes); on timeout the whole process tree is killed and the run
  fails instead of hanging the batch.
- On Windows, `python` in test commands resolves to the running interpreter
  after `$env:` prefixes, and POSIX `NAME=value cmd` prefixes work.
- `patch.diff` records the submitted patch instead of an enclosing repository's
  unrelated changes.
- `score_recompute__risk_cpu_incident` runs pytest verbosely so its
  pass-to-pass tests can be matched.

### Fixed: agents

- Patch extraction keeps blank context lines written as empty lines, multi-file
  diffs with plain headers, and one fenced block per file; previously these were
  truncated or corrupted, so correct fixes scored as failures.
- A reply cut off at the output token limit is treated as invalid and repaired
  instead of applied.
- Anthropic requests have a timeout and retry rate-limit and overload errors;
  `max_tokens` can be set in the code agent's profile section.
- JSON `null` fields in ops assessments are treated as empty, so the repair loop
  runs, instead of grading the text "None".
- `AzureOpenAIOpsAgent` defaults to `AZURE_OPENAI_API_KEY` as documented.
- With `hide_fault_location`, repositories without `src/*.py` (all Go
  scenarios) now show their source files; previously the prompt had none.

### Fixed: CLI, evaluation and scripts

- Batch mode (`--manifest`) honours `--dry-run`, `--disable-coupling`,
  `--allow-synthetic-ops`, `--agent-config`, agent references and model flags,
  and rejects single-scenario flags. `diagnostics.json` records
  `disable_coupling` and the effective models.
- Scenarios whose ops fault comes from a third-party source are no longer
  reported as not ready.
- Inline `model_patch` predictions are written inside the run directory rather
  than into the repository.
- `update_leaderboard.py` handles non-ASCII and backslashes in names, decides
  the 0–1 or 0–100 scale once per file, and writes `null` for modes that were
  not evaluated; the website shows those as Pending.
- `run_agent_evals.py` names default outputs after the profile so runs do not
  overwrite each other, and `--no-keep-artifacts` works.
- The diagnosis leakage gate fails when a diagnosis's fix diff cannot be found
  instead of passing it unchecked.

### Fixed: experiment harness (`volt/`)

These affect future runs only; archived results are unchanged.

- Directional feedback compared each attempt against the best *scoring*
  attempt, so until one beat the baseline every correct attempt was reported as
  "FASTER … new best", even when it was slower. It now compares against the best
  correct attempt so far, or the baseline.
- Failed runs in `run_experiments.py` are recorded as 0-score rows with an
  `error` column instead of being dropped from the denominator.
- The perf loop treats a benchmark that exits non-zero as failed, and skips a
  scenario whose baseline benchmark produced nothing.
- B/op and allocs/op are read correctly when a benchmark reports MB/s.
- Line-level profile feedback finds the hot function when pprof marks it inline.
- `run_perf_sweep.py` skips scenarios whose gold patch does not apply, pass or
  speed things up, instead of normalizing scores against it.
- The previous diff shown to the model now matches the feedback it is shown.
- `pl_v4provllm_2n_A/B.yaml` use SGLang, as their descriptions say.

### Added

- `ACBENCH_RUNS_DIR` sets where run outputs are written. The test suite uses it
  and no longer writes into `runs/`.

### Website

- The leaderboard is labelled as v0.1.0 results, since they were scored before
  the changes above.
- Pages deploys only from a public repository.

### Known issues

- The perf harness runs `go test` without a scenario's `-tags` or `-run`
  options, which may have excluded two candidate scenarios during gold
  validation.

## [0.1.0] - 2026-06-17

Initial publication release.
