"""Pricing helpers for the local billing fixture."""

from __future__ import annotations


def subtotal_cents(lines: list[dict[str, int | str]]) -> int:
    """Compute a cart subtotal in cents."""

    total = 0
    for line in lines:
        total += int(line["unit_price_cents"]) * int(line["quantity"])
    return total


def _eligible_bundle_units(lines: list[dict[str, int | str]]) -> int:
    """Count units that are eligible for the bundle discount."""

    total = 0
    for line in lines:
        if line.get("category") == "gift-card":
            continue
        total += int(line["quantity"])
    return total


def bundle_discount_rate(lines: list[dict[str, int | str]]) -> float:
    """Return the best bundle discount rate for the cart."""

    eligible_units = _eligible_bundle_units(lines)
    if eligible_units > 3:
        return 0.10
    if eligible_units >= 2 and len(lines) >= 2:
        return 0.05
    return 0.0


def invoice_total_cents(
    lines: list[dict[str, int | str]],
    *,
    coupon_percent: int = 0,
    shipping_cents: int = 0,
) -> int:
    """Compute the final invoice total after promotions and shipping."""

    subtotal = subtotal_cents(lines)
    bundle_discount = int(round(subtotal * bundle_discount_rate(lines)))
    after_bundle = subtotal - bundle_discount
    coupon_discount = int(round(after_bundle * (coupon_percent / 100)))
    return after_bundle - coupon_discount + shipping_cents
