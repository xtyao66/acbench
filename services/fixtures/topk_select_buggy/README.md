# topk-select-buggy

Local ACBench measured-performance fixture for the `topk_heap` archetype.

The candidate-selection handler in `src/topk_select/handler.py` answers each
request by returning the best `k` candidates from a scored pool. It does so by
**fully ordering the entire pool** (`sorted(...)[:k]`) and then throwing away
everything past the first `k`. Fully ordering `N` candidates costs `O(N log N)`
comparisons even when only a tiny `k` is requested, so per-request CPU time
tracks the size of the whole pool rather than the small result it returns.

`src/topk_select/ranking.py` defines the `RankKey` comparator (higher score
wins, ties broken by ascending id) and **counts every ordering comparison** it
performs. The comparison is deliberately resolved in Python rather than by
handing a plain tuple to C-level Timsort, so each comparison is real, countable
CPU work and reducing the number of comparisons reduces real wall-clock time.

The counting regression test in `tests/test_handler.py` drives the selection
over a pool of `N` candidates with a small `k` and bounds the comparison cost on
**both** sides: it must stay well under the `O(N log N)` full-sort cost (so the
buggy full sort fails) *and* clear a floor of ~`N` comparisons (so a patch that
bypasses the real comparator -- e.g. by sorting on a throwaway plain key, which
would dodge the cost entirely -- cannot sneak past). The behavioral tests pin the
selected output (value, rank order, tie-break, and the empty / `k<=0` / `k>N`
edge cases) so a fast-but-wrong or degenerate "return nothing" patch fails.

The fix is to select only the top `k` with a bounded heap
(`heapq.nlargest(k, keys)`, i.e. `O(N log k)`) instead of fully ordering the
pool -- no behavioral change to the selected candidates, only to the algorithmic
cost of the pass.

## Measured performance

`bench.py` drives `select_top_k` over a pool of `N = 600000` candidates with
`k = 10` and prints one JSON line `{"elapsed_s": <float>, "n": ..., "k": ...}`.
The grader (`volt/measure_perf.py`) copies the fixture, applies the gold patch,
gates on correctness via `pytest tests/`, then times `bench.py` on the baseline
and the candidate taking the MIN over repeats: `speedup = base_min / cand_min`.
Measured on the reference machine the baseline runs ~0.8-0.9 s and the heap
selection ~0.16 s, for a measured speedup of ~5x (target range 3-10x).
