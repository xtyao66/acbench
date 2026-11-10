"""Tests for the feature router fixture."""

from __future__ import annotations

import unittest

from feature_router.router import choose_variant


class FeatureRouterTests(unittest.TestCase):
    def test_denylist_overrides_percent_rollout(self) -> None:
        variant = choose_variant(
            "blocked-user",
            rollout_percent=100,
            denylist={"blocked-user"},
        )
        self.assertEqual(variant, "control")

    def test_allowlist_user_gets_new_even_with_zero_rollout(self) -> None:
        variant = choose_variant(
            "staff-user",
            rollout_percent=0,
            allowlist={"staff-user"},
        )
        self.assertEqual(variant, "new")

    def test_regular_user_stays_control_when_rollout_zero(self) -> None:
        variant = choose_variant(
            "regular-user",
            rollout_percent=0,
        )
        self.assertEqual(variant, "control")


if __name__ == "__main__":
    unittest.main()
