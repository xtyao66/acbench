"""Tests for the standalone-first repository layout."""

from __future__ import annotations

import importlib
import unittest
from pathlib import Path

from acbench.models.scenario import ScenarioSpec


class StandaloneLayoutTests(unittest.TestCase):
    def test_canonical_task_scenarios_load(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for relative_path in (
            "tasks/scenarios/local/code/billing_pricing__bundle_discount_threshold.scenario.json",
            "tasks/scenarios/local/code/feature_router__denylist_precedence.scenario.json",
            "tasks/scenarios/local/code/maintenance_window__overnight_rollover.scenario.json",
            "tasks/scenarios/local/ops/cache_api__stale_index_alert.scenario.json",
            "tasks/scenarios/local/ops/queue_worker__backlog_spike.scenario.json",
            "tasks/scenarios/local/ops/payments_api__restart_loop_diagnosis.scenario.json",
            "tasks/scenarios/local/combined/billing_pricing__checkout_totals_incident.scenario.json",
            "tasks/scenarios/local/combined/feature_router__rollout_guard_incident.scenario.json",
            "tasks/scenarios/local/combined/maintenance_window__midnight_skip_incident.scenario.json",
            "tasks/scenarios/github/code/openclaw__pairing_state_array_persistence.scenario.json",
            "tasks/scenarios/github/code/openclaw__no_reply_prefix_leak.scenario.json",
            "tasks/scenarios/github/ops/openclaw__docker_healthcheck_false_unhealthy.scenario.json",
            "tasks/scenarios/github/ops/openclaw__mcp_tool_hard_timeout.scenario.json",
            "tasks/scenarios/github/combined/openclaw__completion_process_leak_incident.scenario.json",
            "tasks/scenarios/github/combined/openclaw__discord_slash_done_incident.scenario.json",
        ):
            scenario = ScenarioSpec.from_file(root / relative_path)
            self.assertTrue(scenario.scenario_id)

    def test_new_namespace_packages_are_importable(self) -> None:
        for module_name in (
            "acbench.orchestrator",
            "acbench.tasks",
            "acbench.services",
            "acbench.evaluation",
            "acbench.executors.backends.code",
            "acbench.executors.backends.ops",
        ):
            module = importlib.import_module(module_name)
            self.assertIsNotNone(module)


if __name__ == "__main__":
    unittest.main()
