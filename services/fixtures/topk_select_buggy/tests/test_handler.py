"""Tests for the top-K candidate-selection handler.

``test_topk_selection_scales_sublinearly_in_pool`` is the performance oracle: it
counts ``RankKey`` comparisons deterministically (no wall-clock timing) and fails
on the full-sort implementation, whose comparison cost grows as O(N log N) in the
pool size even when only a tiny ``k`` is requested. The behavioral tests pin the
selected output -- value, ordering, tie-break, and edge cases -- so a fast but
wrong rewrite (or a degenerate "return nothing" patch) cannot earn credit.
"""

from __future__ import annotations

import math
import unittest

from topk_select.handler import select_top_k
from topk_select.ranking import Candidate, comparison_count


def _ids(candidates: list[Candidate]) -> list[str]:
    return [c.candidate_id for c in candidates]


def _pairs(candidates: list[Candidate]) -> list[tuple[str, int]]:
    return [(c.candidate_id, c.score) for c in candidates]


class TopKSelectTests(unittest.TestCase):
    def test_topk_selection_scales_sublinearly_in_pool(self) -> None:
        # Performance oracle. Selecting the top ``k`` from a pool of ``n`` must
        # cost a number of comparisons close to O(n log k), NOT O(n log n). A
        # full comparison sort of the pool costs >= n*log2(n)/2 comparisons; a
        # bounded top-k selection costs O(n log k). With k tiny and n large the
        # gap is wide, so we cap the budget well below the full-sort cost.
        n, k = 4000, 8
        candidates = [
            Candidate(candidate_id=f"cand-{i:05d}", score=(i * 2654435761) % 1009)
            for i in range(n)
        ]
        select_top_k(candidates, k)
        comparisons = comparison_count()

        full_sort_lower_bound = 0.5 * n * math.log2(n)  # ~24000 for n=4000
        # Upper bound: a correct bounded-heap selection stays a small multiple of
        # n; allow a generous constant factor but stay far under the full-sort
        # lower bound. The buggy full-sort path needs >> this and so fails here.
        budget = 6 * n  # 24000; the full-sort path needs far more than this
        self.assertLess(
            comparisons,
            budget,
            f"top-{k} selection used {comparisons} comparisons "
            f"(full-sort needs >= {full_sort_lower_bound:.0f}); it is still "
            f"fully sorting the pool",
        )
        # Lower bound: the ordering MUST actually be decided by the service's
        # RankKey comparator. A genuine top-k pass touches every candidate against
        # the running selection, so it performs at least ~n RankKey comparisons.
        # This blocks a patch that bypasses the real comparator (e.g. by sorting
        # on a plain throwaway key) -- which would record zero comparisons and so
        # dodge the cost the incident is about -- from sneaking past the oracle.
        floor = n // 2  # 2000; any real RankKey-based selection clears this
        self.assertGreaterEqual(
            comparisons,
            floor,
            f"top-{k} selection recorded only {comparisons} RankKey comparisons; "
            f"the ranking must be resolved through the candidate comparator, not "
            f"bypassed",
        )

    def test_selects_best_k_in_rank_order(self) -> None:
        # Distinct scores: the result must be the k highest, ordered best first.
        candidates = [
            Candidate("a", 10),
            Candidate("b", 50),
            Candidate("c", 30),
            Candidate("d", 90),
            Candidate("e", 70),
        ]
        result = select_top_k(candidates, 3)
        self.assertEqual(_pairs(result), [("d", 90), ("e", 70), ("b", 50)])

    def test_ties_broken_by_ascending_id(self) -> None:
        # Equal scores must be broken deterministically by ascending id, and the
        # tie-break must hold exactly at the k boundary.
        candidates = [
            Candidate("zeta", 5),
            Candidate("alpha", 5),
            Candidate("mike", 5),
            Candidate("bravo", 5),
            Candidate("yard", 1),
        ]
        result = select_top_k(candidates, 3)
        # All score 5; ascending id => alpha, bravo, mike (zeta/yard excluded).
        self.assertEqual(_ids(result), ["alpha", "bravo", "mike"])

    def test_returns_exactly_min_k_and_len(self) -> None:
        candidates = [Candidate("x", 3), Candidate("y", 9), Candidate("z", 1)]
        # k larger than the pool returns the whole pool, still best-first.
        self.assertEqual(_pairs(select_top_k(candidates, 10)), [("y", 9), ("x", 3), ("z", 1)])
        # k smaller than the pool returns exactly k.
        self.assertEqual(len(select_top_k(candidates, 2)), 2)

    def test_empty_and_nonpositive_k(self) -> None:
        self.assertEqual(select_top_k([], 5), [])
        self.assertEqual(select_top_k([Candidate("a", 1)], 0), [])
        self.assertEqual(select_top_k([Candidate("a", 1)], -3), [])


if __name__ == "__main__":
    unittest.main()
