"""Ranking primitives for the candidate-selection service.

A retrieval/recommendation worker scores a large pool of candidates and must
return only the best ``k`` of them, ranked highest score first. The score is a
composite value, so two candidates are ordered by a real, multi-field key:
score (descending), then a deterministic tie-break over the candidate's id.

``RankKey`` wraps that ordering in a comparison object whose ``__lt__`` performs
the actual field-by-field comparison and is **counted**. The count lets a
regression test assert the *algorithmic cost* of a selection pass deterministically
-- a full comparison sort costs O(n log n) comparisons, while pulling only the
top ``k`` with a bounded heap costs O(n log k). The comparison itself is genuine
Python-level work, so reducing the number of comparisons reduces real CPU time.
"""

from __future__ import annotations

from dataclasses import dataclass


# Module-level comparison counter. ``RankKey.__lt__`` bumps it on every ordering
# decision so a test can measure how many comparisons a selection pass costs
# without any wall-clock timing. ``reset_comparison_count`` zeroes it per pass.
_COMPARISONS = {"count": 0}


def reset_comparison_count() -> None:
    """Zero the global comparison counter before a selection pass."""

    _COMPARISONS["count"] = 0


def comparison_count() -> int:
    """Return how many ``RankKey`` comparisons have happened since the last reset."""

    return _COMPARISONS["count"]


@dataclass(frozen=True)
class Candidate:
    """A scored candidate to be ranked."""

    candidate_id: str
    score: int


class RankKey:
    """Total order in which a *better* candidate compares as *greater*.

    "Better" means: higher score, or -- on a tie -- a smaller candidate_id (so
    the candidate that should rank earlier is the larger key). Defining the order
    this way lets both selection strategies agree on the top-``k``: a descending
    full sort and ``heapq.nlargest`` both surface the greatest keys first.

    The comparison is intentionally done in Python (not by handing a plain tuple
    to C-level Timsort) so that every ordering decision is real, countable work.
    Reducing the number of comparisons therefore reduces real CPU time.
    """

    __slots__ = ("candidate",)

    def __init__(self, candidate: Candidate) -> None:
        self.candidate = candidate

    def __lt__(self, other: "RankKey") -> bool:
        # Count this ordering decision, then resolve it field by field. ``self``
        # is "less than" ``other`` when ``self`` is the *worse* candidate.
        _COMPARISONS["count"] += 1
        a = self.candidate
        b = other.candidate
        if a.score != b.score:
            # Lower score is worse -> compares as "less than".
            return a.score < b.score
        # Equal score: the larger id is the worse candidate (it should rank
        # later), so a larger id compares as "less than". This keeps the order
        # total and the tie-break stable across runs.
        return a.candidate_id > b.candidate_id
