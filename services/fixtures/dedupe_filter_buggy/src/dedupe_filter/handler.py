"""Event-ingestion de-duplication handler.

The ingestion worker receives a batch of inbound events and must forward only
the ones it has not already accepted during this run. Each event names an
``event_id``; the handler keeps a running index of accepted ids so duplicates --
whether redelivered by the upstream queue or repeated within the same batch --
are dropped. The returned list preserves input order and contains each accepted
event exactly once.
"""

from __future__ import annotations

from dedupe_filter.seen_index import SeenIndex


def filter_new_events(
    events: list[dict[str, str]],
    seen: SeenIndex,
) -> list[dict[str, str]]:
    """Return the events whose id has not been accepted yet, in input order.

    For each event we test whether its id is already in the running ``seen``
    index; if not, the event is accepted and its id recorded. Ids already
    present (from an earlier batch or earlier in this batch) are skipped.
    """

    accepted: list[dict[str, str]] = []
    for event in events:
        event_id = event["event_id"]
        # Repeated linear membership scan: ``event_id in seen`` walks the entire
        # growing list of already-seen ids on every iteration. For a batch of N
        # fresh events this is O(N^2) element comparisons.
        if event_id in seen:
            continue
        seen.add(event_id)
        accepted.append(event)
    return accepted
