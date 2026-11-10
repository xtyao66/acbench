"""Tests for the billing pricing fixture."""

from __future__ import annotations

import unittest

from billing_pricing.pricing import invoice_total_cents


class PricingTests(unittest.TestCase):
    def test_exactly_three_eligible_units_trigger_bundle_discount(self) -> None:
        total = invoice_total_cents(
            [
                {
                    "sku": "starter-kit",
                    "category": "physical",
                    "unit_price_cents": 1000,
                    "quantity": 3,
                }
            ],
            coupon_percent=10,
            shipping_cents=500,
        )
        self.assertEqual(total, 2930)

    def test_gift_cards_do_not_count_toward_bundle_threshold(self) -> None:
        total = invoice_total_cents(
            [
                {
                    "sku": "ebook",
                    "category": "digital",
                    "unit_price_cents": 2000,
                    "quantity": 1,
                },
                {
                    "sku": "gift-card",
                    "category": "gift-card",
                    "unit_price_cents": 1500,
                    "quantity": 2,
                },
            ],
            shipping_cents=0,
        )
        self.assertEqual(total, 5000)

    def test_two_distinct_items_get_small_bundle_discount(self) -> None:
        total = invoice_total_cents(
            [
                {
                    "sku": "mug",
                    "category": "physical",
                    "unit_price_cents": 1000,
                    "quantity": 1,
                },
                {
                    "sku": "beans",
                    "category": "physical",
                    "unit_price_cents": 600,
                    "quantity": 1,
                },
            ],
        )
        self.assertEqual(total, 1520)


if __name__ == "__main__":
    unittest.main()
