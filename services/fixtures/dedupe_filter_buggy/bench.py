"""Performance driver: exercise the hot path at a scale where the algorithmic
cost dominates measurement noise. Prints one JSON line: elapsed_s + workload."""
import json, sys, time
sys.path.insert(0, "src")
from dedupe_filter.handler import filter_new_events
from dedupe_filter.seen_index import SeenIndex
N = 12000
events = [{"event_id": f"e{i}"} for i in range(N)]
seen = SeenIndex()
t = time.perf_counter(); out = filter_new_events(events, seen); dt = time.perf_counter() - t
print(json.dumps({"elapsed_s": dt, "n": N, "accepted": len(out)}))
