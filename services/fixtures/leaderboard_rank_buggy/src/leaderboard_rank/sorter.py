"""Tiny in-repo sort instrument that counts how often a list is sorted.

This stands in for the (potentially expensive) ranking sort a leaderboard
service performs. Every call to :meth:`SortMeter.sorted_desc` increments
``sort_count`` by exactly one so a regression test can assert how many times the
scoreboard was re-sorted, deterministically and without any wall-clock timing.
"""

from __future__ import annotations


class SortMeter:
    """Sorts score rows by score (descending) and counts each sort it performs."""

    def __init__(self) -> None:
        # Number of full re-sorts performed. A leaderboard only needs to rank
        # its players once per request; re-sorting per player is the bug.
        self.sort_count = 0

    def sorted_desc(self, rows: list[tuple[str, int]]) -> list[tuple[str, int]]:
        """Return ``rows`` ordered by score descending, ties broken by player id.

        Each call counts as exactly one sort, whether it ranks one player or the
        entire scoreboard.
        """

        self.sort_count += 1
        return sorted(rows, key=lambda row: (-row[1], row[0]))
