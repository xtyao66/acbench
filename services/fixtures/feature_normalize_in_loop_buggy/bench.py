"""Performance driver: exercise the hot path at a scale where the algorithmic
cost dominates measurement noise. Prints one JSON line: elapsed_s + workload.

The buggy scorer recomputes the reference-cohort column statistics once per
applicant, so its cost is O(batch * cohort_rows * cohort_cols). N (the batch
size) and the cohort dimensions are chosen so the slow baseline runs ~0.5-2 s.
"""
import json, sys, time

sys.path.insert(0, "src")
from feature_scorer.scorer import score_batch
from feature_scorer.reference import ColumnStats

N = 800            # applicants in the batch (the loop the bug multiplies over)
COHORT_ROWS = 1500  # reference-cohort records
COLS = 8            # features per record

# Deterministic synthetic data (no external deps): a fixed pseudo cohort and
# batch generated from a simple recurrence so every run scores the same input.
cohort = [
    [((i * 7 + j * 13) % 97) / 11.0 + 0.5 for j in range(COLS)]
    for i in range(COHORT_ROWS)
]
applicants = [
    [((i * 5 + j * 3) % 89) / 9.0 + 0.25 for j in range(COLS)]
    for i in range(N)
]

stats = ColumnStats()
t = time.perf_counter()
out = score_batch(applicants, cohort, stats)
dt = time.perf_counter() - t
print(json.dumps({"elapsed_s": dt, "n": N, "scored": len(out)}))
