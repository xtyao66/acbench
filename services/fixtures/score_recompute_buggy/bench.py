"""Performance driver: exercise the hot path at a scale where the redundant
recomputation cost dominates measurement noise. Prints one JSON line:
elapsed_s + workload.

The batch holds N events drawn from only ``UNIQUE`` distinct profile keys, the
way a real abuse stream sees the same actors over and over. A handler that
re-runs the pure risk model per event does N full computations; one that
memoizes does only ``UNIQUE``.
"""
import json
import sys
import time

sys.path.insert(0, "src")
from score_recompute.handler import score_events

N = 3000
UNIQUE = 150
# Deterministic, heavily repeating stream: each profile key recurs ~N/UNIQUE
# times across the batch (interleaved, not blocked, like real traffic).
events = [{"profile_key": f"actor-{i % UNIQUE}"} for i in range(N)]

t = time.perf_counter()
out = score_events(events)
dt = time.perf_counter() - t

print(json.dumps({"elapsed_s": dt, "n": N, "unique": UNIQUE, "scored": len(out)}))
