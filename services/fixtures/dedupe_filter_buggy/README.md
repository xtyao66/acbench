# dedupe-filter-buggy

Local ACBench performance fixture for the `quadratic_membership` archetype.

The event-ingestion de-duplication handler in `src/dedupe_filter/handler.py`
decides which inbound events are new by testing `event_id in seen` against a
running index of already-accepted ids. Because that membership test is a
**linear scan over a list that keeps growing**, de-duplicating a batch of `N`
events costs roughly `N^2/2` element comparisons — the cost grows quadratically
with batch size and dominates CPU time when batches get large.

`src/dedupe_filter/seen_index.py` is a tiny in-repo instrumented index that
**counts every element comparison** it performs. The linear `x in index`
(`__contains__`) access counts one comparison per stored id it touches, while
the hashed `index.has(x)` access counts exactly one comparison regardless of
size. The counting regression test in `tests/test_handler.py` drives the
handler over a batch of `N` distinct events and asserts the membership cost stays
**linear in N**. It fails on the repeated-linear-scan implementation (~N^2/2
comparisons) and passes once membership is resolved with the hashed lookup (~N).

The fix is to test membership against a hash-backed structure (`index.has(...)`,
i.e. a set/dict lookup) instead of scanning the ordered list — no behavioral
change to the filtered events, only to the algorithmic cost of the pass.
