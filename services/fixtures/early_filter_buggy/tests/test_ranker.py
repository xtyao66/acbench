"""Tests for the top-K candidate ranking hot path.

``test_scores_only_eligible_candidates`` is the performance oracle: it counts
how many times the expensive relevance score is computed and fails on the
materialise-everything-then-filter implementation, which scores every candidate
including the ineligible ones. The remaining tests pin the ranked output (and
its ordering / tie-breaking / eligibility semantics) so a fast-but-wrong rewrite
that drops or reorders results cannot earn credit.
"""

from __future__ import annotations

import unittest

import early_filter.scoring as scoring
from early_filter.ranker import rank_top_k


def _doc(doc_id, tokens, active=True, locale="en-US"):
    return {"doc_id": doc_id, "tokens": list(tokens), "active": active, "locale": locale}


class _ScoreCounter:
    """Context manager that counts calls to ``scoring.score_candidate``.

    The ranker imports ``score_candidate`` into its own module namespace, so we
    patch it there as well to observe every invocation the hot path makes.
    """

    def __init__(self):
        self.calls = 0

    def __enter__(self):
        import early_filter.ranker as ranker_mod

        self._orig = scoring.score_candidate
        self._ranker_mod = ranker_mod
        self._orig_in_ranker = ranker_mod.score_candidate

        def counting(candidate, query_terms):
            self.calls += 1
            return self._orig(candidate, query_terms)

        scoring.score_candidate = counting
        ranker_mod.score_candidate = counting
        return self

    def __exit__(self, *exc):
        scoring.score_candidate = self._orig
        self._ranker_mod.score_candidate = self._orig_in_ranker
        return False


class RankTopKTests(unittest.TestCase):
    def test_scores_only_eligible_candidates(self) -> None:
        # Performance oracle: the expensive relevance score must be computed
        # only for candidates that pass the cheap eligibility predicate. Here
        # exactly 3 of the 9 candidates are eligible (active, locale en-US, not
        # blocked), so an early-filtering implementation scores 3 candidates,
        # while a materialise-everything-then-filter pass scores all 9.
        candidates = [
            _doc("d0", ["alpha"], active=True, locale="en-US"),   # eligible
            _doc("d1", ["alpha"], active=False, locale="en-US"),  # inactive
            _doc("d2", ["alpha"], active=True, locale="fr-FR"),   # wrong locale
            _doc("d3", ["alpha"], active=True, locale="en-US"),   # eligible
            _doc("d4", ["alpha"], active=False, locale="fr-FR"),  # inactive+locale
            _doc("d5", ["alpha"], active=True, locale="en-US"),   # blocked below
            _doc("d6", ["alpha"], active=True, locale="de-DE"),   # wrong locale
            _doc("d7", ["alpha"], active=False, locale="en-US"),  # inactive
            _doc("d8", ["alpha"], active=True, locale="en-US"),   # eligible
        ]
        blocked = {"d5"}
        with _ScoreCounter() as counter:
            rank_top_k(candidates, ("alpha",), "en-US", blocked, top_k=10)
        # 3 eligible candidates -> at most 3 score computations. A small slack of
        # one keeps the guard robust, but a full-materialisation pass (9 scores)
        # blows past it.
        self.assertLessEqual(counter.calls, 4)

    def test_returns_top_k_by_score_then_doc_id(self) -> None:
        # All eligible; scores differ by how many query terms overlap. Highest
        # score first; ties broken by ascending doc_id.
        candidates = [
            _doc("d-c", ["alpha", "alpha", "alpha", "x"]),  # 3 matches
            _doc("d-a", ["alpha", "bravo", "x", "x"]),      # 2 matches
            _doc("d-b", ["alpha", "bravo", "y", "y"]),      # 2 matches (tie w/ d-a)
            _doc("d-d", ["zzz", "yyy"]),                    # 0 matches
        ]
        out = rank_top_k(candidates, ("alpha", "bravo"), "en-US", set(), top_k=3)
        ids = [r["doc_id"] for r in out]
        # d-c has the highest overlap; d-a and d-b tie on score so ascending
        # doc_id puts d-a before d-b. d-d (zero score) is excluded by top_k=3.
        self.assertEqual(ids, ["d-c", "d-a", "d-b"])
        # Scores must be returned and sorted descending.
        scores = [r["score"] for r in out]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertAlmostEqual(out[1]["score"], out[2]["score"])

    def test_excludes_ineligible_and_handles_edges(self) -> None:
        candidates = [
            _doc("keep-1", ["alpha"], active=True, locale="en-US"),
            _doc("drop-inactive", ["alpha"], active=False, locale="en-US"),
            _doc("drop-locale", ["alpha"], active=True, locale="fr-FR"),
            _doc("drop-blocked", ["alpha"], active=True, locale="en-US"),
            _doc("keep-2", ["alpha"], active=True, locale="en-US"),
        ]
        out = rank_top_k(
            candidates, ("alpha",), "en-US", {"drop-blocked"}, top_k=10
        )
        ids = sorted(r["doc_id"] for r in out)
        self.assertEqual(ids, ["keep-1", "keep-2"])

        # Empty candidate list -> empty result.
        self.assertEqual(rank_top_k([], ("alpha",), "en-US", set(), top_k=5), [])
        # top_k == 0 -> empty result even with eligible candidates.
        self.assertEqual(
            rank_top_k(candidates, ("alpha",), "en-US", set(), top_k=0), []
        )
        # No eligible candidate at all (wrong locale for everyone) -> empty.
        self.assertEqual(
            rank_top_k(candidates, ("alpha",), "zz-ZZ", set(), top_k=5), []
        )

    def test_top_k_truncates_to_highest_scores(self) -> None:
        # More eligible candidates than top_k: only the highest-scoring survive.
        candidates = [
            _doc("hi", ["alpha", "alpha", "alpha"]),  # 3 matches
            _doc("mid", ["alpha", "alpha"]),          # 2 matches
            _doc("lo", ["alpha"]),                    # 1 match
        ]
        out = rank_top_k(candidates, ("alpha",), "en-US", set(), top_k=2)
        self.assertEqual([r["doc_id"] for r in out], ["hi", "mid"])


if __name__ == "__main__":
    unittest.main()
