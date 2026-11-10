"""Tests for the localized listener-runtime reproduction."""

from __future__ import annotations

import unittest

from openclaw_listener_runtime.agent_loop import AgentRuntime


class AgentRuntimeTests(unittest.TestCase):
    def test_listener_events_during_active_run_are_processed(self) -> None:
        runtime = AgentRuntime()
        runtime.start_run("run-001")

        outcome = runtime.process_listener_event("whatsapp", "hello")

        self.assertEqual(outcome, "processed")
        self.assertEqual(runtime.processed_events, [("whatsapp", "hello")])

    def test_finishing_a_run_clears_the_active_run(self) -> None:
        runtime = AgentRuntime()
        runtime.start_run("run-002")

        runtime.finish_run()

        self.assertIsNone(runtime.active_run_id)

    def test_listener_events_outside_active_run_are_skipped(self) -> None:
        runtime = AgentRuntime()

        outcome = runtime.process_listener_event("whatsapp", "late-message")

        self.assertEqual(outcome, "skipped")
        self.assertEqual(runtime.processed_events, [])
        self.assertEqual(len(runtime.warnings), 1)


if __name__ == "__main__":
    unittest.main()
