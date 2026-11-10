"""Top-K candidate-selection handler.

The selection worker scores a large pool of candidates and must return only the
best ``k`` of them, ranked best first. "Best" is defined by :class:`RankKey`:
higher score wins, ties broken by ascending candidate id. The returned list
contains exactly ``min(k, len(candidates))`` candidates, ordered best first.
"""

from __future__ import annotations

from topk_select.ranking import Candidate, RankKey, reset_comparison_count


def select_top_k(
    candidates: list[Candidate],
    k: int,
) -> list[Candidate]:
    """Return the ``k`` best candidates, ranked best first.

    Only the top ``k`` are ever needed downstream, but this implementation pays
    for a *full* ordering of the entire pool and then throws almost all of it
    away.
    """

    reset_comparison_count()
    if k <= 0 or not candidates:
        return []

    keys = [RankKey(candidate) for candidate in candidates]

    # Fully sort the entire candidate pool, then keep only the first ``k``.
    # Sorting N candidates costs O(N log N) comparisons even though only the top
    # ``k`` are needed; for k << N this throws away almost all of the work. Each
    # comparison is a real ``RankKey.__lt__`` call, so the wasted comparisons are
    # wasted CPU time, not just wasted asymptotics.
    ordered = sorted(keys, reverse=True)
    top = ordered[:k]

    return [key.candidate for key in top]
