"""Tests for the reference-cohort feature scorer.

``test_cohort_passes_independent_of_batch_size`` is the performance oracle: it
counts full passes over the reference cohort deterministically (no wall-clock
timing) and fails on the recompute-in-loop implementation, whose pass count
grows with the batch size. The correctness tests pin the scored output so a
fast-but-wrong rewrite (one that hoists by changing behavior, drops applicants,
or skips the normalization) cannot earn credit.
"""

from __future__ import annotations

import math
import unittest

from feature_scorer.scorer import score_batch
from feature_scorer.reference import ColumnStats


def _reference_score(
    applicants: list[list[float]], cohort: list[list[float]]
) -> list[float]:
    """Independent, deliberately naive score computation used as ground truth.

    Computed without the production code path so it pins behavior rather than
    mirroring the implementation: a z-score term plus a cohort-proximity term.
    """

    n_cols = len(cohort[0])
    n_rows = len(cohort)
    means = [sum(row[j] for row in cohort) / n_rows for j in range(n_cols)]
    stds = [
        max(
            math.sqrt(
                sum((row[j] - means[j]) ** 2 for row in cohort) / n_rows
            ),
            1e-9,
        )
        for j in range(n_cols)
    ]
    out = []
    for applicant in applicants:
        z_term = sum(
            (applicant[j] - means[j]) / stds[j] for j in range(n_cols)
        )
        proximity = sum(
            sum((applicant[j] - row[j]) ** 2 for j in range(n_cols))
            for row in cohort
        ) / n_rows
        out.append(z_term + proximity)
    return out


# Cohort + batch shared by the behavioral guards. Small but multi-column and
# with non-trivial spread so the normalization actually matters.
_COHORT = [
    [1.0, 10.0, 100.0, 4.0],
    [3.0, 12.0, 130.0, 4.0],
    [5.0, 9.0, 160.0, 4.0],
    [2.0, 15.0, 110.0, 4.0],
    [4.0, 11.0, 140.0, 4.0],
]
_APPLICANTS = [
    [3.0, 11.0, 120.0, 4.0],
    [1.0, 9.0, 100.0, 4.0],
    [5.0, 14.0, 160.0, 4.0],
]


class FeatureScorerTests(unittest.TestCase):
    def test_cohort_passes_independent_of_batch_size(self) -> None:
        # Performance oracle: computing the reference-cohort column statistics
        # must touch the cohort a number of times that does NOT grow with the
        # batch size. The hoisted scorer computes the statistics exactly once
        # regardless of how many applicants are scored; a per-applicant
        # recompute makes one statistics pass per applicant. Allow a tiny
        # constant slack so the oracle pins the SHAPE, not an exact count.
        big_batch = [[3.0, 11.0, 120.0, 4.0] for _ in range(40)]
        stats = ColumnStats()
        score_batch(big_batch, _COHORT, stats)
        self.assertLessEqual(stats.cohort_passes, 2)

    def test_scores_match_reference_z_scores(self) -> None:
        # Behavioral correctness: the scores must equal an independent z-score
        # computation. A fast-but-wrong patch that skips normalization, drops
        # the mean/stddev, or returns the raw sum fails here.
        stats = ColumnStats()
        got = score_batch(_APPLICANTS, _COHORT, stats)
        expected = _reference_score(_APPLICANTS, _COHORT)
        self.assertEqual(len(got), len(expected))
        for g, e in zip(got, expected):
            self.assertAlmostEqual(g, e, places=9)

    def test_preserves_input_order_and_count(self) -> None:
        # Every applicant is scored exactly once, in input order. A reordered or
        # de-duplicated output (e.g. from accidentally keying on values) fails.
        applicants = [
            [3.0, 11.0, 120.0, 4.0],
            [3.0, 11.0, 120.0, 4.0],  # identical twin: must NOT be collapsed
            [5.0, 14.0, 160.0, 4.0],
        ]
        stats = ColumnStats()
        got = score_batch(applicants, _COHORT, stats)
        self.assertEqual(len(got), 3)
        # The two identical applicants get identical scores; the third differs.
        self.assertAlmostEqual(got[0], got[1], places=9)
        self.assertNotAlmostEqual(got[0], got[2], places=6)

    def test_empty_batch_returns_empty(self) -> None:
        # Edge case: an empty batch yields an empty score list and never raises.
        stats = ColumnStats()
        self.assertEqual(score_batch([], _COHORT, stats), [])

    def test_single_applicant_matches_reference(self) -> None:
        # Edge case: a one-element batch still normalizes against the full cohort.
        stats = ColumnStats()
        got = score_batch([_APPLICANTS[0]], _COHORT, stats)
        expected = _reference_score([_APPLICANTS[0]], _COHORT)
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(got[0], expected[0], places=9)


if __name__ == "__main__":
    unittest.main()
