"""Tiny in-repo fake audit-event store that records how much it reads.

This stands in for an external table / row store. It exposes two access paths:

* ``scan_all`` materializes **every** row in the table -- a full-table scan.
* ``query`` pushes a tenant + severity predicate down so the store only
  materializes the rows that actually match.

Both paths increment ``rows_returned`` by the number of rows they hand back, so
a regression test can assert how much data a handler pulls out of the store --
deterministically and without any wall-clock timing. ``scan_count`` records how
many distinct table reads were issued.
"""

from __future__ import annotations

# Ordered severities, lowest to highest. A row matches a query when its severity
# ranks at or above the requested threshold.
SEVERITY_ORDER = ["debug", "info", "warning", "error", "critical"]


def _severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.index(severity)


class EventStore:
    """A fake audit-event store that records how many rows it returns."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = [dict(row) for row in rows]
        # Total number of rows handed back to callers across all reads. Both
        # ``scan_all`` and ``query`` add the size of the result they return.
        self.rows_returned = 0
        # Number of distinct table reads served.
        self.scan_count = 0

    def scan_all(self) -> list[dict[str, object]]:
        """Return every row in the table (a full-table scan).

        The store materializes and counts the entire table regardless of how
        few rows the caller ultimately keeps.
        """

        self.scan_count += 1
        self.rows_returned += len(self._rows)
        return [dict(row) for row in self._rows]

    def query(
        self, tenant_id: str, min_severity: str
    ) -> list[dict[str, object]]:
        """Return only rows for ``tenant_id`` at or above ``min_severity``.

        The predicate is evaluated inside the store, so only matching rows are
        materialized and counted (a predicate-pushed read).
        """

        self.scan_count += 1
        threshold = _severity_rank(min_severity)
        matches = [
            dict(row)
            for row in self._rows
            if row["tenant_id"] == tenant_id
            and _severity_rank(str(row["severity"])) >= threshold
        ]
        self.rows_returned += len(matches)
        return matches
