"""Performance driver: exercise the hot path at a scale where the algorithmic
cost dominates measurement noise. Prints one JSON line: elapsed_s + workload.

The batch carries ``N`` metering records spread across ``G`` distinct tenants
(``G`` grows with ``N``, mirroring a platform whose batch and tenant counts grow
together). The buggy "find the group" linear scan over the growing group list
makes the roll-up cost ~O(N*G); the defaultdict fix makes it O(N)."""
import json, sys, time
sys.path.insert(0, "src")
from group_metrics.aggregator import aggregate_by_tenant

G = 2500            # distinct tenants (grows with the batch)
REPEAT = 40         # records per tenant
N = G * REPEAT      # total metering records in the batch

# Interleave tenants so each tenant's records are spread through the batch, the
# way a real time-ordered metering stream arrives. The first-seen order of
# tenants is t0000000, t0000001, ... so output order is deterministic.
records = [
    {"tenant_id": f"t{i % G:07d}", "units": (i % 9) + 1}
    for i in range(N)
]

t = time.perf_counter(); out = aggregate_by_tenant(records); dt = time.perf_counter() - t
print(json.dumps({"elapsed_s": dt, "n": N, "groups": len(out)}))
