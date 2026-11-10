"""Per-tenant usage-metrics roll-up.

The billing aggregator receives a flat batch of metering records, one per API
call, and must roll them up **by tenant**: for every distinct ``tenant_id`` it
emits a single group carrying the tenant's id, the number of records seen and
the summed ``units``. Groups are returned in the order each tenant's *first*
record appears in the batch, and every input record contributes to exactly one
group.

The roll-up is the hot path of the nightly billing job: a batch can carry one
record per API call across every tenant on the platform, so both the number of
records *and* the number of distinct tenants grow together as the platform does.
"""

from __future__ import annotations


class Group:
    """An accumulator for one tenant's metering records."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.count = 0
        self.total_units = 0

    def add(self, units: int) -> None:
        self.count += 1
        self.total_units += units

    def as_dict(self) -> dict[str, int | str]:
        return {"key": self.key, "count": self.count, "total_units": self.total_units}


def aggregate_by_tenant(records: list[dict[str, object]]) -> list[dict[str, int | str]]:
    """Roll a batch of metering records up into one group per ``tenant_id``.

    Each record is a mapping with a ``tenant_id`` and an integer ``units``. The
    returned list holds one group per distinct tenant, in first-seen order, each
    with the tenant's record ``count`` and summed ``total_units``.
    """

    groups: list[Group] = []
    for record in records:
        tenant_id = record["tenant_id"]
        units = record["units"]

        # "Find the group" by linear scan: walk the whole list of groups built
        # so far looking for the one whose key matches this tenant. As distinct
        # tenants accumulate, this scan grows with the batch, so rolling up N
        # records across G tenants costs O(N*G) -- quadratic when G grows with N.
        target = None
        for group in groups:
            if group.key == tenant_id:
                target = group
                break
        if target is None:
            target = Group(tenant_id)
            groups.append(target)

        target.add(units)

    return [group.as_dict() for group in groups]
