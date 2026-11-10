"""Tests for the quote pricing engine.

``test_memoizes_rate_computation_per_unique_zone`` is the performance oracle: it
counts how many times the expensive *pure* rate model runs (no wall-clock
timing) and fails on the per-line implementation, which recomputes the surcharge
for every line even when zones repeat. The correctness tests pin the priced
output so the memoized rewrite cannot earn credit by changing behavior.
"""

from __future__ import annotations

import unittest

from quote_pricing.engine import price_quote
from quote_pricing.rates import RateCalculator


def _make_rates() -> RateCalculator:
    return RateCalculator()


def _make_line_items() -> list[dict[str, object]]:
    # Six lines but only four distinct zones: ``us-west`` and ``us-east`` repeat.
    return [
        {"sku": "SKU-A", "zone": "us-west", "amount": 10000},
        {"sku": "SKU-B", "zone": "us-east", "amount": 5000},
        {"sku": "SKU-C", "zone": "us-west", "amount": 20000},
        {"sku": "SKU-D", "zone": "apac", "amount": 8000},
        {"sku": "SKU-E", "zone": "mars", "amount": 3000},
        {"sku": "SKU-F", "zone": "us-east", "amount": 5000},
    ]


def _unique_zone_count(line_items: list[dict[str, object]]) -> int:
    return len({item["zone"] for item in line_items})


class QuotePricingTests(unittest.TestCase):
    def test_memoizes_rate_computation_per_unique_zone(self) -> None:
        rates = _make_rates()
        line_items = _make_line_items()
        price_quote(line_items, rates)
        # Performance oracle: the expensive, pure rate model must run at most
        # once per *unique* zone, no matter how many lines repeat that zone.
        self.assertLessEqual(rates.call_count, _unique_zone_count(line_items))

    def test_prices_each_line_in_order(self) -> None:
        rates = _make_rates()
        priced = price_quote(_make_line_items(), rates)
        self.assertEqual(
            [(p["sku"], p["zone"]) for p in priced],
            [
                ("SKU-A", "us-west"),
                ("SKU-B", "us-east"),
                ("SKU-C", "us-west"),
                ("SKU-D", "apac"),
                ("SKU-E", "mars"),
                ("SKU-F", "us-east"),
            ],
        )

    def test_applies_surcharge_totals_and_unknown_zone_fallback(self) -> None:
        rates = _make_rates()
        priced = price_quote(_make_line_items(), rates)
        totals = [p["total"] for p in priced]
        self.assertEqual(totals[0], 10120)
        self.assertEqual(totals[1], 5052)
        self.assertEqual(totals[2], 20240)
        self.assertEqual(totals[3], 8117)
        # Unknown zone falls back to the model's default surcharge.
        self.assertEqual(totals[4], 3030)
        # The same zone always yields the same surcharge/total.
        self.assertEqual(totals[5], totals[1])


if __name__ == "__main__":
    unittest.main()
