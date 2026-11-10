# feature-normalize-buggy

Local ACBench performance fixture for the `hoist_invariant` archetype.

The risk-scoring worker in `src/feature_scorer/scorer.py` scores a batch of
applicant feature vectors against a fixed **reference cohort** (a matrix of
historical records loaded once at startup). Each applicant's score combines a
**z-score term** (every feature normalized against the cohort's per-column mean
and standard deviation) and a **proximity term** (mean squared distance from the
applicant to every cohort row).

The per-column mean and standard deviation are a property of the cohort alone —
they do **not** depend on which applicant is being scored. But the handler
recomputes the full column-statistics pass over the entire reference matrix once
for *every* applicant in the batch. That makes the per-applicant cohort work
roughly twice what it needs to be: the statistics are a **loop-invariant** that
should be computed once *before* the scoring loop. The proximity term genuinely
depends on the applicant and must stay in the loop.

`src/feature_scorer/reference.py` provides an instrumented `ColumnStats` that
performs the real arithmetic (summing and squaring every cohort element, so the
cost scales with `rows * columns`) and **counts every full pass over the cohort
matrix** in `cohort_passes`. The counting regression test in
`tests/test_scorer.py` drives the scorer over a batch and asserts the number of
statistics passes stays independent of the batch size. It fails on the
recompute-in-loop implementation (one pass per applicant) and passes once the
statistics are hoisted out of the loop (exactly one pass).

The fix is to compute `means, stds = stats.column_stats(cohort)` once before the
`for applicant in applicants:` loop and reuse the result — no behavioral change
to the scores, only to the algorithmic cost of the pass. `bench.py` exercises
the hot path at a scale where the redundant per-applicant statistics work
dominates measurement noise (batch of 800 applicants against a 1500×8 cohort),
and the hoist lands a ~2.4x measured speedup.
