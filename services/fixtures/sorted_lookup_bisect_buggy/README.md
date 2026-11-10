# sorted-lookup-bisect-buggy

Local ACBench measured-performance fixture for the `sorted_lookup_bisect`
archetype.

The request tier-routing handler in `src/tier_router/handler.py` labels every
inbound request with the tier that owns its numeric `key`. Tiers are defined by
a shared, **pre-sorted** boundary table (`src/tier_router/tier_table.py`). The
lookup `table.tier_of(key)` **linearly scans the sorted boundary list from the
front** on every call, so routing a batch of `Q` requests against a table of `N`
boundaries costs `O(Q * N)` boundary comparisons — the per-query cost grows with
the size of the table even though the table is already sorted, and it dominates
CPU time when the table or the batch gets large.

`TierTable` is instrumented: it **counts every boundary comparison** in
`probe_count`. A linear scan touches up to `N` boundaries per key; a halving
(binary) search touches `~log2(N)`. The counting regression test in
`tests/test_handler.py` drives a few keys spread across a large table and
asserts the probe cost stays **logarithmic in N**. It fails on the linear-scan
implementation (`O(N)` probes per query) and passes once the lookup uses a
halving search over the sorted table (`O(log N)` probes).

`bench.py` at the fixture root measures the same hot path on real hardware:
it builds an `N`-boundary table, routes `Q` keys, and prints a single JSON line
`{"elapsed_s": ..., "n": N, "q": Q, "routed": ...}`.

The fix is to exploit the fact that the boundary list is **sorted** and resolve
each key with a binary search (Python's `bisect`) instead of scanning from the
front — `O(N)` per query becomes `O(log N)` per query, with **no behavioral
change** to the routed tiers, only to the algorithmic cost of the pass.
