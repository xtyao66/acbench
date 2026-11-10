"""Daily settlement-rollup aggregation.

At end-of-day the payments service rolls up every captured line-item amount in a
merchant's batch into a single settlement figure: the gross total to be paid out,
the number of line items rolled up, and the mean line amount. Amounts arrive as a
flat list of currency values (already normalized to a single currency and sign:
positive for captures, negative for refunds), so the rollup is a pure numeric
aggregation over a large list.

The rollup is on the hot path of the nightly settlement job: a single large
merchant can settle tens of millions of line items in one batch, so the cost of
the aggregation pass dominates the job's CPU time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settlement:
    """Result of rolling up one batch of line-item amounts.

    ``total`` is the gross settlement amount, ``count`` the number of line items
    rolled up, and ``mean`` the average line amount (``0.0`` for an empty batch).
    """

    total: float
    count: int
    mean: float


def roll_up_settlement(amounts: list[float]) -> Settlement:
    """Aggregate a batch of line-item ``amounts`` into a single settlement.

    Returns the gross ``total`` of every amount, the ``count`` of line items, and
    the ``mean`` line amount. Input order does not affect the total. An empty
    batch settles to ``Settlement(0.0, 0, 0.0)``.
    """

    count = len(amounts)

    # Elementwise accumulation: walk the entire batch one line item at a time in
    # Python, adding each amount onto a running total. Every iteration pays the
    # full per-element interpreter overhead (bytecode dispatch, boxing the
    # intermediate float), so for a batch of N line items the rollup costs N slow
    # Python-level additions instead of one bulk pass.
    total = 0.0
    for amount in amounts:
        total = total + amount

    mean = total / count if count else 0.0
    return Settlement(total=total, count=count, mean=mean)
