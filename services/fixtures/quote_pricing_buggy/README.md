# quote-pricing-buggy

Local ACBench performance fixture for the `missing_memoization` archetype.

The quote pricing engine in `src/quote_pricing/engine.py` resolves a zone
surcharge for every order line by calling an **expensive, pure rate model once
per line** inside a loop. For a batch of `N` lines that is `N` invocations of the
model, even though many lines repeat the same zone and the result depends only on
the zone. The redundant recomputation dominates CPU time as orders grow.

`src/quote_pricing/rates.py` is a tiny in-repo rate calculator that **counts every
invocation** of the expensive computation. The counting regression test in
`tests/test_engine.py` prices a batch of lines that share zones and asserts the
model ran **at most once per unique zone**. It fails on the per-line
implementation (one call per line) and passes once the result is memoized per
distinct zone.

The fix is to memoize the pure rate computation — compute each distinct zone's
surcharge once and reuse it for the remaining lines — with no behavioral change to
the priced output, only to how many times the expensive model runs.
