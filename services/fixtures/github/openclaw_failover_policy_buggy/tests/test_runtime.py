"""Tests for the localized failover-policy reproduction."""

from __future__ import annotations

import unittest

from openclaw_failover_policy.runtime import decide_main_lane_action


class FailoverPolicyTests(unittest.TestCase):
    def test_single_transport_error_still_retries(self) -> None:
        self.assertEqual(
            decide_main_lane_action(1, "transport"),
            "retry",
        )

    def test_non_transport_errors_surface_immediately(self) -> None:
        self.assertEqual(
            decide_main_lane_action(1, "auth"),
            "surface_error",
        )

    def test_three_transport_errors_trigger_immediate_fallback(self) -> None:
        self.assertEqual(
            decide_main_lane_action(3, "transport"),
            "fallback",
        )


if __name__ == "__main__":
    unittest.main()
