# early-filter-buggy

Local ACBench measured-performance fixture for the `early_filter` archetype.

The top-K candidate ranking endpoint in `src/early_filter/ranker.py` returns the
`top_k` *eligible* candidates ordered by relevance. A candidate is eligible only
when it is active, in the requested `locale`, and not in the caller's `blocked`
set -- a **cheap** check. Computing the relevance score
(`src/early_filter/scoring.py`) is the **expensive** per-candidate work: it walks
every query term against every document token, so its cost scales with document
size.

The slow implementation **materialises a fully-scored intermediate list for
every candidate first**, and only afterwards drops the ineligible ones and slices
the top-K. That pays the expensive score even for candidates an eligibility check
would have rejected for free. When most of the batch is ineligible, the pipeline
burns CPU scoring documents it then throws away.

The fix is to **filter eligibility first and short-circuit**: only score the
candidates that survive the cheap predicate, and keep a bounded top-K heap rather
than fully sorting every eligible candidate. The returned ranking is unchanged --
same documents, same scores, same order -- only the algorithmic cost of the pass
drops.

`bench.py` drives the hot path over a batch where roughly one in three candidates
is eligible, so early filtering avoids the bulk of the scoring work and the
measured speedup lands in the 1.5-4x range. `tests/test_ranker.py` contains a
score-call-count oracle (fails on the materialise-everything pass) plus
behavioral guards pinning the ranked output, ordering, tie-breaking, and
eligibility semantics so a fast-but-wrong rewrite cannot earn credit.
