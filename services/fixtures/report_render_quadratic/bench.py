"""Performance driver: exercise the hot path at a scale where the algorithmic
cost dominates measurement noise. Prints one JSON line: elapsed_s + workload."""
import json, sys, time
sys.path.insert(0, "src")
from report_render.serializer import render_report

N = 26000
records = [
    {
        "ts": f"2026-06-18T12:{i % 60:02d}:{(i * 7) % 60:02d}Z",
        "level": ("INFO", "WARN", "ERROR")[i % 3],
        "service": f"svc-{i % 32}",
        "message": f"request {i} completed in {i % 250} ms for tenant {i % 97}",
    }
    for i in range(N)
]
t = time.perf_counter(); out = render_report(records); dt = time.perf_counter() - t
print(json.dumps({"elapsed_s": dt, "n": N, "chars": len(out)}))
