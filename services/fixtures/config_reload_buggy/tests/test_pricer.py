"""Tests for the pricing-quote handler.

``test_reads_pricing_config_at_most_once`` is the performance oracle: it counts
config file reads / parses deterministically (no wall-clock timing) and fails on
the read-per-quote implementation, which re-reads the config once per line item.
The correctness tests pin the computed quotes so the load-once rewrite cannot
earn credit by changing behavior.
"""

from __future__ import annotations

import unittest

from config_reload.config_source import PricingConfigSource
from config_reload.pricer import price_quotes


def _make_config() -> PricingConfigSource:
    return PricingConfigSource(
        '{"prices": {"sku-a": 2.5, "sku-b": 4.0, "sku-c": 10.0}}'
    )


def _make_line_items() -> list[dict[str, object]]:
    return [
        {"sku": "sku-a", "quantity": 2},
        {"sku": "sku-b", "quantity": 1},
        {"sku": "sku-c", "quantity": 3},
        {"sku": "sku-b", "quantity": 5},
        {"sku": "sku-z", "quantity": 4},
    ]


class ConfigReloadTests(unittest.TestCase):
    def test_reads_pricing_config_at_most_once(self) -> None:
        config = _make_config()
        price_quotes(_make_line_items(), config)
        # Performance oracle: regardless of how many line items arrive, the
        # handler must read/parse the pricing config at most once per batch.
        self.assertLessEqual(config.read_count, 1)

    def test_prices_each_item_in_order(self) -> None:
        config = _make_config()
        quotes = price_quotes(_make_line_items(), config)
        self.assertEqual(
            [(q["sku"], q["quantity"], q["total"]) for q in quotes],
            [
                ("sku-a", 2, 5.0),
                ("sku-b", 1, 4.0),
                ("sku-c", 3, 30.0),
                ("sku-b", 5, 20.0),
                ("sku-z", 4, 0.0),
            ],
        )

    def test_resolves_unit_prices_and_unknown_fallback(self) -> None:
        config = _make_config()
        quotes = price_quotes(_make_line_items(), config)
        unit_prices = [q["unit_price"] for q in quotes]
        self.assertEqual(unit_prices[0], 2.5)
        self.assertEqual(unit_prices[1], 4.0)
        self.assertEqual(unit_prices[2], 10.0)
        # Unknown SKU falls back to a unit price of 0.0.
        self.assertEqual(unit_prices[4], 0.0)


if __name__ == "__main__":
    unittest.main()
