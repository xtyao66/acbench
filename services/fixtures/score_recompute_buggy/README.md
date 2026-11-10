# score-recompute-buggy

Local ACBench **measured-performance** fixture for the `memoize_recompute`
archetype.

The risk-scoring ingestion handler in `src/score_recompute/handler.py` attaches
a risk score to every inbound event by running an expensive **pure** risk model
(`src/score_recompute/risk_model.py`) on the event's `profile_key`. The model is
genuinely CPU-bound -- each call performs ~1400 rounds of SHA-256 key stretching
-- but its output depends only on the profile key, so it is fully memoizable.

In a real abuse stream the same actors recur constantly, so a batch of `N`
events is drawn from only a small set of distinct profile keys. The buggy
handler invokes the model **once per event**, re-deriving the identical score
for a repeated key again and again: `N` full computations for a batch that has
only a handful of unique keys. That redundant recomputation is where the CPU
time goes.

`bench.py` drives the hot path with `N = 3000` events over `UNIQUE = 150`
distinct keys and prints one JSON line `{"elapsed_s": ..., "n": ..., ...}`. The
grader (`volt/measure_perf.py`) times `bench.py` on the baseline and on a
gold-patched copy and reports `speedup = base_min / cand_min`. Because each key
recurs ~20 times, memoizing the pure model collapses ~3000 computations down to
~150, for a measured speedup well inside the 5-30x target band.

The fix is to memoize the pure risk model so each distinct profile key is
computed at most once -- idiomatically `functools.lru_cache` on the scoring
function -- with **no behavioral change** to the scored output, only to the CPU
cost of the pass. The behavioral tests in `tests/test_handler.py` pin the exact
scored records, their order, and their values, so a fast-but-wrong rewrite (one
that skips work, blanks scores, drops duplicates, or reorders output) fails.
