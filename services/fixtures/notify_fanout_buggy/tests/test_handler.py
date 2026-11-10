"""Tests for the notification fan-out handler.

``test_batches_recipient_lookups_into_single_query`` is the performance oracle:
it counts datastore round-trips deterministically (no wall-clock timing) and
fails on the per-event-loop implementation, which issues one query per event.
The correctness tests pin the rendered output so the batched rewrite cannot earn
credit by changing behavior.
"""

from __future__ import annotations

import unittest

from notify_fanout.handler import build_notifications
from notify_fanout.store import ProfileStore


def _make_store() -> ProfileStore:
    return ProfileStore(
        {
            "u-1": {"display_name": "Ada"},
            "u-2": {"display_name": "Lin"},
            "u-3": {"display_name": "Mei"},
        }
    )


def _make_events() -> list[dict[str, str]]:
    return [
        {"recipient_id": "u-1", "channel": "email", "summary": "your build passed"},
        {"recipient_id": "u-2", "channel": "sms", "summary": "your build passed"},
        {"recipient_id": "u-3", "channel": "email", "summary": "your build passed"},
        {"recipient_id": "u-2", "channel": "push", "summary": "deploy finished"},
        {"recipient_id": "u-99", "channel": "email", "summary": "welcome aboard"},
    ]


class NotifyFanoutTests(unittest.TestCase):
    def test_batches_recipient_lookups_into_single_query(self) -> None:
        store = _make_store()
        build_notifications(_make_events(), store)
        # Performance oracle: regardless of how many events arrive, the handler
        # must resolve recipient profiles with at most one datastore round-trip.
        self.assertLessEqual(store.query_count, 1)

    def test_renders_message_per_event_in_order(self) -> None:
        store = _make_store()
        messages = build_notifications(_make_events(), store)
        self.assertEqual(
            [(m["recipient_id"], m["channel"]) for m in messages],
            [
                ("u-1", "email"),
                ("u-2", "sms"),
                ("u-3", "email"),
                ("u-2", "push"),
                ("u-99", "email"),
            ],
        )

    def test_resolves_display_names_and_unknown_fallback(self) -> None:
        store = _make_store()
        messages = build_notifications(_make_events(), store)
        bodies = [m["body"] for m in messages]
        self.assertEqual(bodies[0], "Hi Ada, your build passed")
        self.assertEqual(bodies[1], "Hi Lin, your build passed")
        self.assertEqual(bodies[3], "Hi Lin, deploy finished")
        # Unknown recipient falls back to a generic greeting.
        self.assertEqual(bodies[4], "Hi there, welcome aboard")


if __name__ == "__main__":
    unittest.main()
