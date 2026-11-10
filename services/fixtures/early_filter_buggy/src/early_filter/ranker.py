"""Top-K candidate ranking for the search/recommendation request path.

The ranking endpoint receives a query and a batch of candidate documents and
must return the ``top_k`` *eligible* candidates ordered by relevance score
(highest first, ties broken by ascending ``doc_id`` for determinism).

A candidate is eligible only when it is active, belongs to the requested
``locale``, and is not in the caller's ``blocked`` set. Eligibility is a cheap
check; computing the relevance score (see ``scoring.score_candidate``) is the
expensive per-candidate work.

The implementation below materialises a fully-scored intermediate list for
*every* candidate up front and only afterwards drops the ineligible ones and
slices the top-K. That means the expensive score is paid even for candidates
that an eligibility check would have rejected for free.
"""

from __future__ import annotations

from early_filter.scoring import score_candidate


def rank_top_k(
    candidates: list[dict],
    query_terms: tuple[str, ...],
    locale: str,
    blocked: set[str],
    top_k: int,
) -> list[dict]:
    """Return the ``top_k`` eligible candidates, highest relevance first.

    Each returned item is ``{"doc_id": ..., "score": ...}``. Ties on score are
    broken by ascending ``doc_id`` so the ordering is fully deterministic.
    """

    # Step 1: score EVERY candidate, building a fully-materialised intermediate
    # list of (candidate, score) pairs -- including candidates that are not even
    # eligible. The expensive ``score_candidate`` call runs for all of them.
    scored: list[tuple[dict, float]] = []
    for candidate in candidates:
        score = score_candidate(candidate, query_terms)
        scored.append((candidate, score))

    # Step 2: now drop the ineligible candidates from the materialised list.
    eligible: list[tuple[dict, float]] = []
    for candidate, score in scored:
        if not candidate["active"]:
            continue
        if candidate["locale"] != locale:
            continue
        if candidate["doc_id"] in blocked:
            continue
        eligible.append((candidate, score))

    # Step 3: fully sort the entire eligible list, then slice the top-K.
    eligible.sort(key=lambda pair: (-pair[1], pair[0]["doc_id"]))

    return [
        {"doc_id": candidate["doc_id"], "score": score}
        for candidate, score in eligible[:top_k]
    ]
