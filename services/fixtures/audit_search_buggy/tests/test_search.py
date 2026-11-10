"""Tests for the audit-log search handler.

``test_pushes_predicate_into_store_query`` is the performance oracle: it counts
how many rows the handler pulls out of the store (no wall-clock timing) and
fails on the fetch-everything-then-filter implementation, which scans the whole
table. The correctness tests pin the returned rows so the predicate-pushed
rewrite cannot earn credit by changing behavior.
"""

from __future__ import annotations

import unittest

from audit_search.search import search_audit_events
from audit_search.store import EventStore


def _make_store() -> EventStore:
    # A table dominated by non-matching rows: many tenants and severities, but
    # only a small subset matches the scoped query exercised below. ``t-7`` rows
    # at >= "warning" are the only matches.
    rows: list[dict[str, object]] = []
    # Noise: 40 rows belonging to other tenants.
    for i in range(40):
        rows.append(
            {
                "event_id": f"n-{i}",
                "tenant_id": f"t-{i % 5}",  # t-0..t-4, never t-7
                "severity": "info",
                "timestamp": 1_000 + i,
                "action": "noise.event",
            }
        )
    # Noise: 10 rows for the target tenant but below the severity threshold.
    for i in range(10):
        rows.append(
            {
                "event_id": f"lo-{i}",
                "tenant_id": "t-7",
                "severity": "info",
                "timestamp": 2_000 + i,
                "action": "login.ok",
            }
        )
    # The 3 rows that actually match: tenant t-7 at >= warning.
    rows.append(
        {
            "event_id": "m-1",
            "tenant_id": "t-7",
            "severity": "warning",
            "timestamp": 3_001,
            "action": "config.changed",
        }
    )
    rows.append(
        {
            "event_id": "m-2",
            "tenant_id": "t-7",
            "severity": "error",
            "timestamp": 3_003,
            "action": "auth.denied",
        }
    )
    rows.append(
        {
            "event_id": "m-3",
            "tenant_id": "t-7",
            "severity": "critical",
            "timestamp": 3_002,
            "action": "secret.exfil",
        }
    )
    return EventStore(rows)


class AuditSearchTests(unittest.TestCase):
    def test_pushes_predicate_into_store_query(self) -> None:
        store = _make_store()
        results = search_audit_events(store, tenant_id="t-7", min_severity="warning")
        matching = len(results)
        # Performance oracle: the handler must pull back no more rows than
        # actually match the scoped query, instead of scanning the whole table.
        self.assertLessEqual(store.rows_returned, matching)

    def test_returns_matching_events_newest_first(self) -> None:
        store = _make_store()
        results = search_audit_events(store, tenant_id="t-7", min_severity="warning")
        # Only the 3 matching rows, ordered newest-first by timestamp.
        self.assertEqual(
            [(r["event_id"], r["severity"], r["timestamp"]) for r in results],
            [
                ("m-2", "error", 3_003),
                ("m-3", "critical", 3_002),
                ("m-1", "warning", 3_001),
            ],
        )

    def test_excludes_other_tenants_and_below_threshold(self) -> None:
        store = _make_store()
        results = search_audit_events(store, tenant_id="t-7", min_severity="warning")
        returned_ids = {r["event_id"] for r in results}
        returned_tenants = {r["tenant_id"] for r in results}
        # No rows from other tenants leak in.
        self.assertEqual(returned_tenants, {"t-7"})
        # The below-threshold "info" rows for t-7 are excluded.
        self.assertFalse(any(rid.startswith("lo-") for rid in returned_ids))
        # Exposes only the public event fields.
        self.assertEqual(
            set(results[0].keys()),
            {"event_id", "tenant_id", "severity", "timestamp", "action"},
        )


if __name__ == "__main__":
    unittest.main()
