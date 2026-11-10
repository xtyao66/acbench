"""A sorted boundary table that maps a numeric key to its tier.

The routing layer assigns every inbound request to a *tier* based on a numeric
score (a priority, a rate-limit weight, a price band -- the exact meaning does
not matter here). Tiers are defined by a list of ascending boundary thresholds:
boundary ``i`` opens tier ``i + 1``. A key ``k`` belongs to the tier whose
half-open interval ``[lower, upper)`` contains it. Keys below the first boundary
land in tier ``0``; keys at or above the last boundary land in the top tier.

The table is built once and queried on the hot path for every request. Its job
is purely the *lookup*: given a key, return the index of the tier that owns it.

This module is intentionally instrumented: every boundary comparison performed
while resolving a key is counted in ``probe_count`` so a regression test can
assert the *algorithmic cost* of a lookup deterministically -- with no
wall-clock timing. A linear scan of the sorted boundaries touches ``O(n)``
boundaries per key; a halving search touches ``O(log n)``.
"""

from __future__ import annotations


class TierTable:
    """Map a numeric key to a tier index over a sorted boundary table.

    ``boundaries`` is a strictly ascending list of thresholds. The table is
    immutable once constructed. ``tier_of`` is the hot-path query.
    """

    def __init__(self, boundaries: list[int]) -> None:
        # Defensive copy so callers cannot mutate the table out from under us.
        self._boundaries: list[int] = list(boundaries)
        # Total boundary comparisons performed across all lookups. Lets a test
        # distinguish an O(n) linear scan from an O(log n) halving search
        # without timing anything.
        self.probe_count = 0

    def __len__(self) -> int:
        return len(self._boundaries)

    def tier_of(self, key: int) -> int:
        """Return the tier index owning ``key``.

        A key is in tier ``t`` when ``boundaries[t-1] <= key < boundaries[t]``
        (with the obvious open ends). The result is in ``[0, len(boundaries)]``.

        This implementation walks the sorted boundary list from the front,
        comparing ``key`` against each boundary in turn until it finds the first
        boundary the key does not reach. Because the list is scanned linearly,
        resolving one key costs ``O(n)`` boundary comparisons, and routing a
        batch of ``Q`` requests costs ``O(Q * n)`` overall -- the per-query cost
        grows with the size of the table even though the table is sorted.
        """

        tier = 0
        for boundary in self._boundaries:
            self.probe_count += 1
            if key < boundary:
                # First boundary the key does not reach: this is its tier.
                return tier
            tier += 1
        # Key is at or above every boundary -> the top tier.
        return tier
