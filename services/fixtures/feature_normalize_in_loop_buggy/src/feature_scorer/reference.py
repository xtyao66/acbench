"""Reference-cohort statistics with an instrumented scan counter.

``ColumnStats`` computes the per-column mean and standard deviation of a
reference cohort matrix in a single traversal. The arithmetic is genuinely
performed -- summing and squaring every element of the cohort -- so the cost is
real CPU work that scales with ``rows * columns``.

It is *also* instrumented: ``cohort_passes`` records how many full passes over
the cohort matrix have been performed across the lifetime of the object. A pass
is one complete traversal of every cohort row. This lets a regression test pin
the *algorithmic shape* of a scoring run deterministically -- a handler that
recomputes the column statistics inside its per-applicant loop performs one such
pass per applicant, whereas a handler that hoists the statistics out of the loop
performs exactly one regardless of batch size.
"""

from __future__ import annotations

import math


class ColumnStats:
    """Computes reference-cohort column statistics and counts cohort passes."""

    def __init__(self) -> None:
        # Number of full statistics traversals of the cohort matrix performed so
        # far. A hoisted scorer makes exactly one; a per-applicant recompute
        # makes one per applicant.
        self.cohort_passes = 0

    def column_stats(
        self, cohort: list[list[float]]
    ) -> tuple[list[float], list[float]]:
        """Per-column (mean, stddev) of the cohort, computed in one pass.

        Uses the sum / sum-of-squares accumulation so mean and standard
        deviation are produced from a single traversal of the matrix. A small
        floor is applied to stddev so a constant column never yields a zero
        divisor downstream.
        """

        self.cohort_passes += 1
        n_cols = len(cohort[0])
        n_rows = len(cohort)
        totals = [0.0] * n_cols
        sq_totals = [0.0] * n_cols
        for row in cohort:
            for j in range(n_cols):
                v = row[j]
                totals[j] += v
                sq_totals[j] += v * v
        means = [totals[j] / n_rows for j in range(n_cols)]
        stds = [
            max(math.sqrt(sq_totals[j] / n_rows - means[j] * means[j]), 1e-9)
            for j in range(n_cols)
        ]
        return means, stds
