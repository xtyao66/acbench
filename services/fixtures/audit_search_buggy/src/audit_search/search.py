"""Audit-log search request handler.

The handler answers a scoped audit query: return every event for a single
tenant whose severity is at or above a requested threshold, newest first. The
matching events are resolved from the audit-event store before they are shaped
into the response rows.
"""

from __future__ import annotations

from audit_search.store import SEVERITY_ORDER, EventStore


def _severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.index(severity)


def search_audit_events(
    store: EventStore,
    tenant_id: str,
    min_severity: str,
) -> list[dict[str, object]]:
    """Return matching audit events for ``tenant_id``, newest first.

    An event matches when it belongs to ``tenant_id`` and its severity ranks at
    or above ``min_severity``. The response preserves a newest-first ordering by
    timestamp and exposes only the public event fields.
    """

    threshold = _severity_rank(min_severity)

    # Pull the entire table out of the store, then filter in Python. For a table
    # with millions of rows this materializes every row even when the scoped
    # query matches only a handful.
    all_rows = store.scan_all()
    matches = [
        row
        for row in all_rows
        if row["tenant_id"] == tenant_id
        and _severity_rank(str(row["severity"])) >= threshold
    ]

    matches.sort(key=lambda row: row["timestamp"], reverse=True)
    return [
        {
            "event_id": row["event_id"],
            "tenant_id": row["tenant_id"],
            "severity": row["severity"],
            "timestamp": row["timestamp"],
            "action": row["action"],
        }
        for row in matches
    ]
