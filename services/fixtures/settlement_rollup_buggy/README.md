# settlement-rollup-buggy

Local ACBench **measured-performance** fixture for the `vectorized_aggregate`
archetype.

The daily settlement rollup in `src/settlement_rollup/rollup.py` aggregates a
merchant's end-of-day batch of line-item amounts into a single settlement figure
(gross total, line count, mean line amount). The amounts arrive as a flat list of
currency values, so the rollup is a pure numeric aggregation over a large list.

The slow implementation accumulates the gross total with an **elementwise Python
loop** -- `for amount in amounts: total = total + amount`. Every iteration pays
the full per-element interpreter overhead (bytecode dispatch, boxing the
intermediate float), so for a batch of `N` line items the rollup costs `N` slow
Python-level additions. On the nightly settlement job a single large merchant can
settle tens of millions of line items in one batch, so this pass dominates the
job's CPU time.

The fix is the `vectorized_aggregate` optimization: replace the hand-written
accumulation loop with **one bulk builtin** -- `total = sum(amounts)` -- which
performs the entire reduction in C with a single call, eliminating the
per-element interpreter overhead. There is no behavioral change to the rolled-up
figures, only to the CPU cost of the pass.

## Measured grading

Unlike the counting-oracle scenarios, this fixture is graded on a **real measured
speedup**. `bench.py` builds an 80M-line batch once (outside the timer) and times
only `roll_up_settlement`, printing one JSON line `{"elapsed_s", "n", "total"}`.
The grader (`volt/measure_perf.py`) times the baseline and the gold-patched
candidate `REPS` times, takes the MIN of each, and reports
`speedup = baseline_min / candidate_min`. On a reference run the baseline rolls up
in ~0.69 s and the bulk-`sum` rewrite in ~0.17 s, a ~4x speedup.

`tests/test_rollup.py` pins the rolled-up output -- total, count, and mean across
empty, single, refund-bearing, duplicate, and order-permuted batches -- so a
fast-but-wrong rewrite (return `0.0`, skip the aggregation, drop or double-count
line items) fails correctness. These tests pass unchanged on both the elementwise
loop and the bulk-`sum` rewrite; only the measured CPU cost moves.
