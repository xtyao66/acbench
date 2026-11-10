"""Tiny in-repo rate calculator that counts how often it is invoked.

This stands in for an expensive, *pure* pricing computation (think a tariff
lookup table walk or a synthetic-benchmark surcharge model). The result depends
only on the zone code, so it is fully memoizable. Every call to
:meth:`RateCalculator.compute` increments ``call_count`` by exactly one so a
regression test can assert how many times the expensive function actually ran,
deterministically and without any wall-clock timing.
"""

from __future__ import annotations


# Per-zone surcharge multipliers (basis points) used by the synthetic model.
_ZONE_FACTORS: dict[str, int] = {
    "us-west": 110,
    "us-east": 95,
    "eu-central": 130,
    "apac": 145,
}


class RateCalculator:
    """A fake, expensive, pure rate model that counts each invocation."""

    def __init__(self) -> None:
        # Number of times the expensive computation actually ran. A correct
        # caller invokes this at most once per *unique* zone.
        self.call_count = 0

    def compute(self, zone: str) -> int:
        """Compute the surcharge (in basis points) for a shipping ``zone``.

        Pure and deterministic: the output depends only on ``zone``. Each call
        counts as exactly one invocation of the expensive model. Unknown zones
        fall back to a default surcharge.
        """

        self.call_count += 1
        base = _ZONE_FACTORS.get(zone, 100)
        # A deterministic "expensive" derivation; still a pure function of zone.
        return base + (len(zone) * 7) % 13
