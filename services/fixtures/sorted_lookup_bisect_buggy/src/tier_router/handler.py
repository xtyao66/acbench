"""Request tier-routing handler.

The routing layer receives a batch of inbound requests, each carrying a numeric
``key``, and must label every request with the tier that owns its key. Tiers are
defined by a shared, pre-sorted :class:`~tier_router.tier_table.TierTable`. The
returned list preserves input order and assigns exactly one tier to each
request.
"""

from __future__ import annotations

from tier_router.tier_table import TierTable


def route_requests(
    requests: list[dict[str, int]],
    table: TierTable,
) -> list[dict[str, int]]:
    """Tag each request with the tier index that owns its ``key``.

    For each request we resolve its key against the sorted ``table`` and attach
    the resulting tier index under ``"tier"``. Input order is preserved and a
    new dict is returned per request so the caller's inputs are not mutated.
    """

    routed: list[dict[str, int]] = []
    for request in requests:
        key = request["key"]
        # Hot-path lookup. ``table.tier_of`` linearly scans the sorted boundary
        # list on every call, so routing a batch of Q requests against a table
        # of N boundaries costs O(Q * N) boundary comparisons.
        tier = table.tier_of(key)
        routed.append({"key": key, "tier": tier})
    return routed
