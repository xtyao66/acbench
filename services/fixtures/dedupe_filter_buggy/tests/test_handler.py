"""Tests for the event-ingestion de-duplication handler.

``test_dedup_membership_scales_linearly`` is the performance oracle: it counts
element comparisons deterministically (no wall-clock timing) and fails on the
repeated-linear-scan implementation, whose cost grows quadratically with the
batch size. The correctness tests pin the filtered output so the hashed rewrite
cannot earn credit by changing behavior.
"""

from __future__ import annotations

import unittest

from dedupe_filter.handler import filter_new_events
from dedupe_filter.seen_index import SeenIndex


# Batch size for the performance oracle. Large enough that an O(n^2) repeated
# membership scan (n*(n-1)/2 comparisons) blows past the linear budget while an
# O(n) hashed membership pass (n comparisons) stays comfortably under it.
_BATCH_SIZE = 64


def _make_unique_events(count: int) -> list[dict[str, str]]:
    return [
        {"event_id": f"evt-{i}", "payload": f"p{i}"}
        for i in range(count)
    ]


def _make_events_with_duplicates() -> list[dict[str, str]]:
    return [
        {"event_id": "evt-a", "payload": "alpha"},
        {"event_id": "evt-b", "payload": "bravo"},
        {"event_id": "evt-a", "payload": "alpha-redelivered"},
        {"event_id": "evt-c", "payload": "charlie"},
        {"event_id": "evt-b", "payload": "bravo-redelivered"},
        {"event_id": "evt-d", "payload": "delta"},
    ]


class DedupeFilterTests(unittest.TestCase):
    def test_dedup_membership_scales_linearly(self) -> None:
        seen = SeenIndex()
        events = _make_unique_events(_BATCH_SIZE)
        filter_new_events(events, seen)
        # Performance oracle: de-duplicating a batch of N events must cost a
        # number of element comparisons that grows linearly with N, not
        # quadratically. A repeated linear membership scan costs ~N^2/2; a
        # hashed membership test costs ~N. Allow a small constant factor.
        self.assertLessEqual(seen.comparison_count, 2 * _BATCH_SIZE)

    def test_keeps_first_occurrence_in_order(self) -> None:
        seen = SeenIndex()
        accepted = filter_new_events(_make_events_with_duplicates(), seen)
        # Duplicates are dropped; the first occurrence of each id is kept, and
        # input order is preserved.
        self.assertEqual(
            [(e["event_id"], e["payload"]) for e in accepted],
            [
                ("evt-a", "alpha"),
                ("evt-b", "bravo"),
                ("evt-c", "charlie"),
                ("evt-d", "delta"),
            ],
        )

    def test_dedup_persists_across_batches(self) -> None:
        seen = SeenIndex()
        first = filter_new_events(
            [
                {"event_id": "evt-1", "payload": "one"},
                {"event_id": "evt-2", "payload": "two"},
            ],
            seen,
        )
        second = filter_new_events(
            [
                {"event_id": "evt-2", "payload": "two-again"},
                {"event_id": "evt-3", "payload": "three"},
            ],
            seen,
        )
        # Ids accepted in the first batch are still remembered for the second,
        # so the second batch only yields the genuinely new id.
        self.assertEqual([e["event_id"] for e in first], ["evt-1", "evt-2"])
        self.assertEqual([e["event_id"] for e in second], ["evt-3"])


if __name__ == "__main__":
    unittest.main()
