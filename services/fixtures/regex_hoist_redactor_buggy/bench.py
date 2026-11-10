"""Performance driver: exercise the hot path at a scale where the per-record
regex-compilation cost dominates measurement noise. Prints one JSON line:
elapsed_s + workload."""
import json, sys, time
sys.path.insert(0, "src")
from payload_redactor.redactor import redact_records

# Batch of N payload records. Each record is a realistic, multi-field log/event
# string repeated a few times so per-record matching work is non-trivial; the
# repeated ruleset *compilation* in the buggy path is what dominates at scale.
N = 1800
_FIELDS = " ; ".join(
    [
        "INFO login user=ada token=abc123XYZ_secretvalue ip=10.0.0.1 mail=ada@example.co",
        "WARN card 4111111111111111 phone (415) 555-2671 ssn 123-45-6789",
        "INFO plain healthcheck status=200 region=us-east latency=12ms node=worker-7",
    ]
)
_RECORD = (_FIELDS + " ") * 8
records = [_RECORD for _ in range(N)]

t = time.perf_counter(); out = redact_records(records); dt = time.perf_counter() - t
print(json.dumps({"elapsed_s": dt, "n": N, "redacted": len(out)}))
