"""Performance driver: exercise the hot path at a scale where the algorithmic
cost dominates measurement noise. Prints one JSON line: elapsed_s + workload.

The selection worker scores a large candidate pool and returns only the best
``k``. We drive it over a large pool with a small ``k`` -- the regime where
selecting the top ``k`` should cost far less than fully ordering the pool."""
import json, sys, time, random
sys.path.insert(0, "src")
from topk_select.handler import select_top_k
from topk_select.ranking import Candidate

N = 600000
K = 10
rng = random.Random(20240617)
# Pseudo-random scores with plenty of ties so the tie-break path is exercised.
candidates = [Candidate(candidate_id=f"cand-{i:06d}", score=rng.randrange(1000)) for i in range(N)]

t = time.perf_counter()
out = select_top_k(candidates, K)
dt = time.perf_counter() - t
print(json.dumps({"elapsed_s": dt, "n": N, "k": K, "selected": len(out)}))
