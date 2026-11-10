"""Feature-scoring service: anomaly scoring against a reference cohort.

The risk-scoring worker receives a batch of applicant feature vectors and must
score each one relative to a fixed *reference cohort* (a matrix of historical
records loaded once at startup). Each applicant's score combines two parts:

* a **z-score term**: every applicant feature is normalized using the reference
  cohort's per-column mean and standard deviation, then summed; and
* a **proximity term**: the mean squared distance from the applicant to every
  cohort row (how far the applicant sits from the historical population).

The per-column mean and standard deviation are a property of the cohort alone --
they do **not** depend on which applicant is being scored. Yet the handler below
recomputes the full column-statistics pass over the entire reference matrix once
for *every* applicant in the batch. The proximity term genuinely depends on the
applicant and must stay in the loop, but the statistics are a loop-invariant
that should be computed once before the scoring loop. Recomputing them per
applicant roughly doubles the per-applicant cohort work for no benefit.
"""

from __future__ import annotations

from feature_scorer.reference import ColumnStats


def score_batch(
    applicants: list[list[float]],
    cohort: list[list[float]],
    stats: ColumnStats,
) -> list[float]:
    """Score each applicant against the reference cohort, in input order."""

    n_cols = len(cohort[0])
    n_rows = len(cohort)

    scores: list[float] = []
    for applicant in applicants:
        # Loop-invariant computation recomputed every iteration: the per-column
        # mean and standard deviation of the reference cohort depend only on the
        # cohort, not on ``applicant``. Computing them here walks the entire
        # reference matrix once per applicant -- pure redundant work.
        means, stds = stats.column_stats(cohort)

        # z-score term: normalize each applicant feature against the cohort.
        z_term = 0.0
        for value, mean, std in zip(applicant, means, stds):
            z_term += (value - mean) / std

        # proximity term: mean squared distance to every cohort row. This part
        # genuinely depends on ``applicant`` and cannot be hoisted out.
        sq_total = 0.0
        for row in cohort:
            for j in range(n_cols):
                diff = applicant[j] - row[j]
                sq_total += diff * diff
        proximity = sq_total / n_rows

        scores.append(z_term + proximity)
    return scores
