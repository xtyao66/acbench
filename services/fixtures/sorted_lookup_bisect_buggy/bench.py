"""Performance driver: exercise the hot path at a scale where the algorithmic
cost dominates measurement noise. Prints one JSON line: elapsed_s + workload."""
import json, sys, time
sys.path.insert(0, "src")
from tier_router.handler import route_requests
from tier_router.tier_table import TierTable

# N sorted boundaries -> N+1 tiers; Q requests routed against the table. The
# buggy linear scan costs O(Q*N); the bisect rewrite costs O(Q*log N).
N = 700
Q = 80000
boundaries = list(range(0, 10 * N, 10))          # strictly ascending thresholds
table = TierTable(boundaries)
# Spread keys across the whole range so lookups land in tiers throughout the
# table (not all near the front, which would flatter the linear scan).
requests = [{"key": (i * 7919) % (10 * N)} for i in range(Q)]

t = time.perf_counter(); out = route_requests(requests, table); dt = time.perf_counter() - t
print(json.dumps({"elapsed_s": dt, "n": N, "q": Q, "routed": len(out)}))
