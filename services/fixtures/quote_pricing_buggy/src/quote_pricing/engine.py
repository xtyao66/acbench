"""Quote pricing engine.

The engine turns a batch of order line items into priced quote lines. Every
line names a shipping ``zone`` whose surcharge must be resolved from the rate
model before the line price can be computed. Many lines in a single order share
the same zone, so the surcharge for a given zone is identical no matter how many
lines reference it.
"""

from __future__ import annotations

from quote_pricing.rates import RateCalculator


def price_quote(
    line_items: list[dict[str, object]],
    rates: RateCalculator,
) -> list[dict[str, object]]:
    """Price every line item in an order.

    For each line we resolve the zone surcharge and apply it to the line's
    ``amount``. The returned list preserves input order. Lines whose zone is
    unknown to the rate model fall back to the model's default surcharge.
    """

    priced: list[dict[str, object]] = []
    for item in line_items:
        zone = item["zone"]
        # The expensive, *pure* surcharge model is recomputed for every line,
        # even when many lines repeat the same zone: N computations for a batch
        # of N lines.
        surcharge = rates.compute(zone)
        amount = int(item["amount"])
        priced.append(
            {
                "sku": item["sku"],
                "zone": zone,
                "amount": amount,
                "total": amount + (amount * surcharge) // 10_000,
            }
        )
    return priced
