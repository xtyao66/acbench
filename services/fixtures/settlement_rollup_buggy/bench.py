"""Performance driver: exercise the settlement-rollup hot path at a scale where
the aggregation cost dominates measurement noise. Builds the batch OUTSIDE the
timed region so only the rollup itself is measured. Prints one JSON line:
elapsed_s + workload."""
import json, random, sys, time
sys.path.insert(0, "src")
from settlement_rollup.rollup import roll_up_settlement

N = 80_000_000
# A large single-merchant end-of-day batch: line-item amounts in cents, a mix of
# captures (positive) and refunds (negative). Built once, outside the timer.
random.seed(20240618)
amounts = [round(random.random() * 200.0 - 50.0, 2) for _ in range(N)]

t = time.perf_counter()
result = roll_up_settlement(amounts)
dt = time.perf_counter() - t

print(json.dumps({"elapsed_s": dt, "n": N, "total": round(result.total, 2)}))
