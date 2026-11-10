"""Behavioral tests for the per-tenant metrics roll-up.

These tests pin the *output* of ``aggregate_by_tenant`` -- the groups, their
first-seen order, their record counts and summed units -- so a faster rewrite
only earns credit if it preserves behavior exactly. A degenerate "fast" patch
that drops records, skips groups, mis-sums units, or reorders the output fails
at least one of these guards.
"""

from __future__ import annotations

import unittest

from group_metrics.aggregator import aggregate_by_tenant


def _records(pairs: list[tuple[str, int]]) -> list[dict[str, object]]:
    return [{"tenant_id": tenant, "units": units} for tenant, units in pairs]


class AggregateByTenantTests(unittest.TestCase):
    def test_groups_counts_and_sums_in_first_seen_order(self) -> None:
        # Tenants interleave; each group must carry the right count and unit
        # total, and the groups must come out in first-seen order (b, a, c).
        records = _records(
            [
                ("b", 5),
                ("a", 2),
                ("b", 3),
                ("c", 10),
                ("a", 4),
                ("b", 1),
            ]
        )
        self.assertEqual(
            aggregate_by_tenant(records),
            [
                {"key": "b", "count": 3, "total_units": 9},
                {"key": "a", "count": 2, "total_units": 6},
                {"key": "c", "count": 1, "total_units": 10},
            ],
        )

    def test_empty_batch_yields_no_groups(self) -> None:
        # Edge case: an empty batch produces no groups (not an error, not a
        # spurious group). Guards against patches that assume non-empty input.
        self.assertEqual(aggregate_by_tenant([]), [])

    def test_every_record_contributes_exactly_once(self) -> None:
        # Conservation: the summed per-group counts equal the number of input
        # records, and the summed per-group units equal the total input units.
        # A patch that drops or double-counts records fails this.
        records = _records(
            [(f"t{i % 7}", (i % 5) + 1) for i in range(50)]
        )
        out = aggregate_by_tenant(records)
        self.assertEqual(sum(g["count"] for g in out), len(records))
        self.assertEqual(
            sum(g["total_units"] for g in out),
            sum(r["units"] for r in records),
        )
        # Exactly the 7 distinct tenants appear, each exactly once.
        keys = [g["key"] for g in out]
        self.assertEqual(sorted(keys), [f"t{i}" for i in range(7)])
        self.assertEqual(len(keys), len(set(keys)))

    def test_single_record_per_tenant_preserves_order(self) -> None:
        # When every tenant is unique, output is one group per record in input
        # order, each with count 1. Guards ordering and the no-merge case.
        records = _records([("z", 1), ("y", 2), ("x", 3)])
        self.assertEqual(
            aggregate_by_tenant(records),
            [
                {"key": "z", "count": 1, "total_units": 1},
                {"key": "y", "count": 1, "total_units": 2},
                {"key": "x", "count": 1, "total_units": 3},
            ],
        )


if __name__ == "__main__":
    unittest.main()
