"""Tiny in-repo instrumented "seen ids" index that counts comparisons.

This stands in for the data structure an ingestion worker keeps in memory to
remember which event ids it has already accepted during a run. Every element
comparison performed while testing membership is counted in
``comparison_count`` so a regression test can assert the *algorithmic cost* of a
de-duplication pass deterministically -- with no wall-clock timing.

Two access patterns are supported, deliberately mirroring the slow and fast
shapes a handler might use:

* ``x in index`` (``__contains__``) performs a **linear scan** and counts one
  comparison per stored id it touches. Used inside a loop this is the classic
  O(n^2) repeated-membership-scan trap.
* ``index.has(x)`` is a **hashed** membership test that counts exactly one
  comparison regardless of how many ids are stored, the way a set/dict lookup
  behaves.

``add`` registers an id in both the ordered backing list and the hash set so
either access pattern stays correct.
"""

from __future__ import annotations


class SeenIndex:
    """An append-only set of "already seen" ids that counts comparisons.

    The container is intentionally instrumented: it records how many element
    comparisons membership testing costs so a test can distinguish an O(n^2)
    repeated linear scan from an O(n) hashed lookup without timing anything.
    """

    def __init__(self) -> None:
        # Ordered backing list scanned by ``__contains__`` (linear membership).
        self._items: list[str] = []
        # Hash set backing the O(1) ``has`` membership test.
        self._index: set[str] = set()
        # Total element comparisons performed across all membership tests.
        self.comparison_count = 0

    def add(self, item: str) -> None:
        """Register an id as seen (kept in both the list and the hash set)."""

        if item not in self._index:
            self._items.append(item)
            self._index.add(item)

    def __contains__(self, item: str) -> bool:
        """Linear-scan membership: counts one comparison per id touched.

        This is the expensive access pattern. Calling ``x in index`` inside a
        loop that also grows the index yields O(n^2) comparisons overall.
        """

        for stored in self._items:
            self.comparison_count += 1
            if stored == item:
                return True
        return False

    def has(self, item: str) -> bool:
        """Hashed membership: counts exactly one comparison, O(1)."""

        self.comparison_count += 1
        return item in self._index

    def __len__(self) -> int:
        return len(self._items)
