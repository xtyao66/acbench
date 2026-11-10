"""Pricing-quote request handler.

The handler turns a batch of line items into priced quotes. Each line item names
a ``sku`` whose unit price must be resolved from the pricing-rules config before
the quote can be computed.
"""

from __future__ import annotations

from config_reload.config_source import PricingConfigSource


def price_quotes(
    line_items: list[dict[str, object]],
    config: PricingConfigSource,
) -> list[dict[str, object]]:
    """Compute a priced quote for every inbound line item.

    For each line item we resolve the SKU's unit price from the pricing config
    and multiply by the requested quantity. The returned list preserves input
    order; line items whose SKU is absent from the config fall back to a unit
    price of 0.0.
    """

    quotes: list[dict[str, object]] = []
    for item in line_items:
        sku = str(item["sku"])
        quantity = int(item["quantity"])
        # Re-read and re-parse the entire pricing config from the backing store
        # on every line item: this loop reads the same unchanged file N times
        # for a batch of N items.
        prices = config.load()
        unit_price = prices.get(sku, 0.0)
        quotes.append(
            {
                "sku": sku,
                "quantity": quantity,
                "unit_price": unit_price,
                "total": round(unit_price * quantity, 2),
            }
        )
    return quotes
