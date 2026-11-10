"""Tests for the localized completion-runtime reproduction."""

from __future__ import annotations

import unittest

from openclaw_completion_runtime.runtime import CompletionRuntime


class CompletionRuntimeTests(unittest.TestCase):
    def test_finished_completion_processes_are_removed_when_session_ends(self) -> None:
        runtime = CompletionRuntime()
        runtime.start_session("session-a")
        runtime.spawn_completion("session-a", 101)
        runtime.mark_completion_finished(101)

        runtime.end_session("session-a")

        self.assertEqual(runtime.orphan_process_count(), 0)
        self.assertNotIn(101, runtime.processes)

    def test_running_completion_processes_are_removed_when_session_ends(self) -> None:
        runtime = CompletionRuntime()
        runtime.start_session("session-a")
        runtime.spawn_completion("session-a", 102)

        runtime.end_session("session-a")

        self.assertNotIn(102, runtime.processes)

    def test_other_sessions_are_not_affected_by_cleanup(self) -> None:
        runtime = CompletionRuntime()
        runtime.start_session("session-a")
        runtime.start_session("session-b")
        runtime.spawn_completion("session-a", 103)
        runtime.spawn_completion("session-b", 104)

        runtime.end_session("session-a")

        self.assertIn(104, runtime.processes)
        self.assertEqual(runtime.processes[104].session_id, "session-b")
        self.assertEqual(runtime.orphan_process_count(), 0)


if __name__ == "__main__":
    unittest.main()
