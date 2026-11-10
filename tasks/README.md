# Task Bank Overview

This directory contains the benchmark task bank used by ACBench.

The task bank is split into two sources:

- `local/`: small, controlled fixtures used to validate the benchmark pipeline end to end
- `github/`: localized reproductions and OpenClaw-style incidents based on real issue patterns

Scenarios live under [tasks/scenarios](scenarios) and are grouped by mode:

- `code`: code repair tasks
- `ops`: incident analysis and remediation tasks
- `combined`: tasks that require both incident reasoning and code repair

Current counts:

- local: `12`
- GitHub-derived: `49`
- total: `61`

## Local Task Bank

### Local code

- `code_only_billing_pricing_bundle_threshold`: Fix the bundle-pricing threshold so a three-item cart receives the correct discount.
- `code_only_feature_router_denylist_precedence`: Fix feature routing so denylist rules override lower-priority allow paths.
- `code_only_maintenance_window_overnight_rollover`: Fix overnight maintenance-window logic so windows that cross midnight are evaluated correctly.

### Local ops

- `ops_only_cache_api_stale_index`: Diagnose a stale cache index that causes the API to serve outdated data.
- `ops_only_queue_worker_backlog_spike`: Diagnose a worker backlog spike that causes queue latency and delayed processing.
- `ops_only_payments_api_restart_loop`: Diagnose a restart loop that keeps the payments API unstable.
- `ops_only_auth_service_token_clock_skew`: Diagnose valid JWTs being rejected due to NTP clock skew between the token issuer and validator nodes.
- `ops_only_db_connection_pool_exhaustion`: Diagnose a connection pool exhaustion incident caused by a long-running uncommitted transaction.
- `ops_only_notifier_dead_letter_queue_overflow`: Diagnose a dead letter queue overflow caused by a malformed webhook payload for a specific event type.

### Local combined

- `combined_billing_pricing_checkout_totals`: Triage a checkout-pricing incident and then fix the bundle-pricing bug.
- `combined_feature_router_rollout_guard`: Triage a rollout-guard incident and then fix the feature-router precedence bug.
- `combined_maintenance_window_midnight_skip`: Triage a midnight scheduling incident and then fix the overnight maintenance-window bug.

## GitHub-Derived OpenClaw Task Bank

### GitHub code

- `github_code_openclaw_pairing_state_array_persistence`: Fix pairing-state loading so array-shaped state files no longer block device approval.
- `github_code_openclaw_gpt5_overlay_aggregator_provider`: Fix GPT-5 overlay matching so aggregator-backed providers still receive the overlay.
- `github_code_openclaw_minimax_usage_get_method`: Fix the MiniMax quota request so the remains endpoint uses the correct HTTP method.
- `github_code_openclaw_no_reply_prefix_leak`: Fix silent-reply detection so `NO_REPLY` plus trailing text is suppressed.
- `github_code_openclaw_plugin_schema_cycle_guard`: Fix schema traversal so circular `$ref` graphs do not recurse forever.
- `github_code_openclaw_completion_cleanup_finished_workers`: Fix runtime cleanup so finished completion workers are removed when sessions end.
- `github_code_openclaw_listener_late_message_guard`: Fix the listener guard so late events after run teardown are skipped instead of crashing.
- `github_code_openclaw_listener_cron_run_guard`: Fix late cron-run listener events so they do not crash the gateway after teardown.
- `github_code_openclaw_listener_telegram_reply_loss_guard`: Fix late listener callbacks so Telegram replies are not lost during delivery recovery.
- `github_code_openclaw_listener_subprocess_stdout_guard`: Fix late subprocess stdout handling so post-run output is discarded safely.
- `github_code_openclaw_memory_status_cfg_context`: Fix memory-status fallback resolution so the active config context is preserved.
- `github_code_openclaw_memory_status_missing_counts_render`: Fix memory-status rendering so missing file and chunk counts are omitted cleanly.
- `github_code_openclaw_discord_native_status_card`: Fix native Discord `/status` handling so it returns the real status card instead of `Done`.
- `github_code_openclaw_discord_plugin_routing_shortcuts`: Fix Discord dispatch so native shortcuts do not fall into the plugin-command fallback.
- `github_code_openclaw_discord_multi_account_shortcuts`: Fix Discord multi-account shortcut handling so native interactions still return content.

### GitHub ops

- `github_ops_openclaw_docker_healthcheck_false_unhealthy`: Diagnose a Docker healthcheck that marks a healthy OpenClaw gateway as unhealthy.
- `github_ops_openclaw_main_lane_failover_too_slow`: Diagnose failover behavior that is too slow to prevent user-visible degradation.
- `github_ops_openclaw_configured_timeout_ignored`: Diagnose why configured long request timeouts are ignored at runtime.
- `github_ops_openclaw_mcp_tool_hard_timeout`: Diagnose a hardcoded 60-second timeout that truncates MCP tool calls.
- `github_ops_openclaw_upgrade_missing_bundled_entry`: Diagnose an upgrade failure caused by a missing bundled setup entry.
- `github_ops_openclaw_status_deep_false_invalid_config`: Diagnose why `status --deep` falsely reports a healthy memory provider as invalid.
- `github_ops_openclaw_discord_slash_done_no_content`: Diagnose Discord slash commands that acknowledge with `Done` but send no real content.
- `github_ops_openclaw_discord_status_done_after_upgrade`: Diagnose why `/status` still degrades to `Done` after an upgrade.
- `github_ops_openclaw_discord_multi_account_shortcuts_broken`: Diagnose Discord shortcut and slash-command regressions in multi-account setups.
- `github_ops_openclaw_discord_new_reset_done`: Diagnose why `/new` stops resetting the conversation correctly.
- `github_ops_openclaw_listener_whatsapp_crash`: Diagnose a gateway crash triggered by a WhatsApp message after the active run ends.
- `github_ops_openclaw_listener_cron_run_crash`: Diagnose a listener crash triggered by late `cron run` output.
- `github_ops_openclaw_listener_telegram_reply_loss`: Diagnose Telegram reply loss caused by a late-listener crash during delivery recovery.
- `github_ops_openclaw_listener_subagent_residual_output`: Diagnose residual subagent output that reaches the listener after cleanup.
- `github_ops_openclaw_pi_agent_abort_state_corruption`: Diagnose runtime-state corruption caused by late callbacks after a pi-agent abort.
- `github_ops_openclaw_redis_session_eviction_storm`: Diagnose Redis session keys being evicted under memory pressure causing mass user logouts.
- `github_ops_openclaw_grpc_deadline_exceeded_cascade`: Diagnose a hardcoded gRPC deadline shorter than actual backend latency causing cascading upstream timeouts.
- `github_ops_openclaw_worker_oom_killed_silent`: Diagnose a background worker silently exiting after an OOM kill with no configured restart policy.
- `github_ops_openclaw_rate_limiter_shared_key_collision`: Diagnose a rate limiter key missing a tenant identifier causing cross-tenant throttling.

### GitHub combined

- `github_combined_openclaw_completion_process_leak`: Triage completion-worker memory pressure and then fix the cleanup path that leaks finished workers.
- `github_combined_openclaw_listener_outside_active_run`: Triage a late-listener gateway crash and then fix the missing active-run guard.
- `github_combined_openclaw_status_deep_false_invalid_config`: Triage a false invalid-config incident and then fix memory-status config resolution.
- `github_combined_openclaw_discord_slash_done`: Triage Discord slash commands that return `Done` and then fix native command dispatch.
- `github_combined_openclaw_slow_failover_degradation`: Triage a slow failover incident and then fix the fallback policy.
- `github_combined_openclaw_pairing_state_array_approval`: Triage a stuck pairing-approval incident and then fix array-shaped pairing-state recovery.
- `github_combined_openclaw_gpt5_overlay_personality_loss`: Triage missing GPT-5 personality overlays and then fix aggregator overlay matching.
- `github_combined_openclaw_minimax_usage_method`: Triage a MiniMax usage outage and then fix the wrong HTTP method on the remains endpoint.
- `github_combined_openclaw_no_reply_prefix_leak`: Triage leaked `NO_REPLY` output and then fix silent-reply prefix handling.
- `github_combined_openclaw_plugin_schema_cycle`: Triage a startup schema-recursion crash and then fix circular schema traversal.
- `github_combined_openclaw_listener_cron_run`: Triage a late cron-run listener crash and then fix the listener guard.
- `github_combined_openclaw_listener_telegram_reply_loss`: Triage dropped Telegram replies and then fix the late-listener guard used during recovery.
- `github_combined_openclaw_listener_subprocess_stdout`: Triage a post-run subprocess-stdout crash and then fix late stdout handling.
- `github_combined_openclaw_discord_plugin_routing_shortcuts`: Triage native Discord shortcuts falling into a plugin fallback and then fix dispatch order.
- `github_combined_openclaw_discord_multi_account_shortcuts`: Triage multi-account Discord shortcut regressions and then fix the native dispatch path.

## Other Scenario Sets

These sets are not part of the 61-scenario core suite counted above:

- `scenarios/perf/`: 26 real-PR Go optimization scenarios. The 14 that passed
  gold validation form the performance-optimization track of the HPEC 2026
  paper ([manifests/perf_real_validated.json](../manifests/perf_real_validated.json)).
- `scenarios/real/`: 14 real-PR incident-to-fix scenarios
  ([manifests/real_prs.json](../manifests/real_prs.json)).
- `scenarios/local/combined/`: 17 local performance-incident fixtures alongside
  the three core combined scenarios
  ([manifests/perf_combined.json](../manifests/perf_combined.json),
  [manifests/perf_measured.json](../manifests/perf_measured.json)).

## Related Files

- scenario definitions: [tasks/scenarios](scenarios)
- local bundle: [manifests/local_suite.json](../manifests/local_suite.json)
- GitHub bundle: [manifests/github_openclaw_extended.json](../manifests/github_openclaw_extended.json)
- authoring guide: [SCENARIO_AUTHORING.md](../docs/SCENARIO_AUTHORING.md)
- task-bank requirements: [TASK_BANK_REQUIREMENTS.md](../docs/TASK_BANK_REQUIREMENTS.md)
