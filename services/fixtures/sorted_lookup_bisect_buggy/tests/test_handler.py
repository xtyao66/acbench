"""Tests for the request tier-routing handler.

``test_lookup_probes_scale_sublinearly`` is the performance oracle: it counts
boundary comparisons deterministically (no wall-clock timing) and fails on the
linear-scan implementation, whose per-query cost grows with the table size. The
remaining tests pin the routing output across ordering, edge, and unknown-key
cases so a fast-but-wrong rewrite (e.g. an off-by-one halving search, or one
that returns ``[]``) cannot earn credit by changing behavior.
"""

from __future__ import annotations

import math
import unittest

from tier_router.handler import route_requests
from tier_router.tier_table import TierTable


# Table size for the performance oracle. Large enough that an O(n) linear scan
# (~n probes per query in the worst case) blows past the logarithmic budget
# while an O(log n) halving search stays comfortably under it.
_TABLE_SIZE = 4096


class TierRoutingTests(unittest.TestCase):
    def test_lookup_probes_scale_sublinearly(self) -> None:
        # Boundaries 10, 20, 30, ... so tier intervals are easy to reason about.
        boundaries = list(range(10, 10 * (_TABLE_SIZE + 1), 10))
        table = TierTable(boundaries)
        # Route a handful of keys spread across the whole table. A linear scan
        # spends O(n) probes on the high keys; a halving search spends O(log n).
        requests = [
            {"key": 5},                       # below first boundary -> tier 0
            {"key": 10 * _TABLE_SIZE // 2},   # middle of the table
            {"key": 10 * _TABLE_SIZE + 5},    # above last boundary -> top tier
            {"key": 10 * _TABLE_SIZE - 5},    # near the end of the table
        ]
        route_requests(requests, table)
        # Performance oracle: resolving Q keys against a table of N boundaries
        # must cost a number of probes that grows logarithmically with N, not
        # linearly. A linear scan costs up to N probes per query; a halving
        # search costs ~log2(N). Allow a generous constant factor.
        budget = len(requests) * 4 * max(1, int(math.log2(_TABLE_SIZE)))
        self.assertLessEqual(table.probe_count, budget)

    def test_routes_keys_to_correct_tiers_in_order(self) -> None:
        # Boundaries [10, 20, 30]: tier 0 = (-inf,10), 1 = [10,20),
        # 2 = [20,30), 3 = [30,inf).
        table = TierTable([10, 20, 30])
        requests = [
            {"key": 5},    # tier 0
            {"key": 10},   # tier 1 (boundary is the lower edge, half-open)
            {"key": 15},   # tier 1
            {"key": 25},   # tier 2
            {"key": 30},   # tier 3 (at last boundary)
            {"key": 99},   # tier 3
        ]
        routed = route_requests(requests, table)
        self.assertEqual(
            [(r["key"], r["tier"]) for r in routed],
            [(5, 0), (10, 1), (15, 1), (25, 2), (30, 3), (99, 3)],
        )

    def test_boundary_keys_use_half_open_intervals(self) -> None:
        # A key exactly equal to a boundary belongs to the tier the boundary
        # OPENS, not the tier below it: [lower, upper). This pins the off-by-one
        # behavior a sloppy bisect (bisect_left vs bisect_right) would get wrong.
        table = TierTable([100, 200, 300])
        routed = route_requests(
            [{"key": 100}, {"key": 200}, {"key": 300}, {"key": 199}],
            table,
        )
        self.assertEqual([r["tier"] for r in routed], [1, 2, 3, 1])

    def test_empty_requests_returns_empty(self) -> None:
        table = TierTable([1, 2, 3])
        self.assertEqual(route_requests([], table), [])

    def test_empty_table_routes_everything_to_tier_zero(self) -> None:
        # With no boundaries there is exactly one tier (0) and every key lands
        # in it. A degenerate lookup that always returns [] or a wrong constant
        # is caught here too.
        table = TierTable([])
        routed = route_requests([{"key": -5}, {"key": 0}, {"key": 1000}], table)
        self.assertEqual([r["tier"] for r in routed], [0, 0, 0])

    def test_preserves_input_order_and_does_not_mutate_inputs(self) -> None:
        table = TierTable([50])
        requests = [{"key": 70}, {"key": 10}, {"key": 50}]
        routed = route_requests(requests, table)
        # Order preserved, correct tiers, originals untouched (no "tier" key).
        self.assertEqual([r["key"] for r in routed], [70, 10, 50])
        self.assertEqual([r["tier"] for r in routed], [1, 0, 1])
        self.assertEqual(requests, [{"key": 70}, {"key": 10}, {"key": 50}])


if __name__ == "__main__":
    unittest.main()
