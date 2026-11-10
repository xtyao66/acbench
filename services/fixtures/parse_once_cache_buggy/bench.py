"""Performance driver: exercise the hot path at a scale where the parsing cost
dominates measurement noise. Prints one JSON line: elapsed_s + workload."""
import json, sys, time
sys.path.insert(0, "src")
from route_config.config_blob import RAW_CONFIG
from route_config.resolver import RouteResolver

# Number of inbound requests resolved against one long-lived resolver. The
# routing config is parsed once at first use in the fixed version; the buggy
# version re-parses the whole document on every one of these N lookups.
N = 35000

# A representative mix of request paths: real routes cycled across the table,
# plus a few unknown ones that fall through to the default backend.
known = [f"/api/v{i % 4}/service-{i:04d}/resource" for i in range(12)]
paths = [known[(i * 5) % len(known)] for i in range(N)]
paths[7::200] = ["/api/v9/does-not-exist/resource"] * len(paths[7::200])

resolver = RouteResolver(RAW_CONFIG)
t = time.perf_counter()
sink = 0
for p in paths:
    sink += len(resolver.resolve(p))
dt = time.perf_counter() - t
print(json.dumps({"elapsed_s": dt, "n": N, "checksum": sink}))
