"""Relevance scoring for ranking candidates.

``score_candidate`` computes a relevance score for a single candidate document
against a query. The score blends term-overlap with a length-normalised decay,
which means it walks every query term against every document term -- genuinely
proportional to ``len(query_terms) * len(doc_terms)`` element comparisons. This
is the real per-candidate CPU cost the ranking pipeline pays, and it is the cost
that dominates when the pipeline scores candidates it is going to throw away.
"""

from __future__ import annotations

import math


def score_candidate(candidate: dict, query_terms: tuple[str, ...]) -> float:
    """Return a relevance score for ``candidate`` against ``query_terms``.

    The score is a term-overlap measure with a length-normalising decay. It is
    deliberately computed term-by-term against the candidate's tokenised body so
    the cost scales with the size of the document -- this is the expensive
    per-candidate work the ranking pipeline performs.
    """

    doc_terms = candidate["tokens"]
    n_doc = len(doc_terms)
    if n_doc == 0:
        return 0.0

    # Count, for every query term, how many times it occurs in the document.
    # This nested walk over the document body is the real cost: it touches every
    # document token for every query term.
    matches = 0
    for q in query_terms:
        for t in doc_terms:
            if t == q:
                matches += 1

    if matches == 0:
        return 0.0

    # Length-normalised, saturating relevance: rewards overlap but damps very
    # long documents so a verbose match does not automatically outrank a tight
    # one. ``log1p`` keeps the score smooth and bounded.
    overlap = matches / len(query_terms)
    length_penalty = 1.0 / (1.0 + math.log1p(n_doc))
    return overlap * length_penalty
