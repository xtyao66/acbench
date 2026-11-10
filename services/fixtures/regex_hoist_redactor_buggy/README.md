# regex-hoist-redactor-buggy

Local ACBench **measured-performance** fixture for the `regex_hoist` archetype.

The request-payload redactor in `src/payload_redactor/redactor.py` masks secrets
and PII (API tokens, credit cards, e-mails, IPs, SSNs, bearer tokens, phone
numbers) out of a batch of payload records before they are forwarded to a
downstream sink. Every record is matched against the same fixed redaction
**ruleset**. Because the handler **re-assembles (parses + compiles) the entire
ruleset inside the per-record loop**, a batch of `N` records invokes the regex
compiler `N` times over even though the ruleset never changes. The recompilation
is pure overhead whose CPU cost grows linearly with the batch size and dominates
the request path at scale.

`src/payload_redactor/regexlab.py` is a tiny in-repo compiler facade that both
(a) does the **genuine** compile work — it parses and compiles every rule with
the standard-library engine on each call, the way building a matcher from
freshly assembled runtime config does — and (b) **counts** how many times a
ruleset was assembled (`COMPILER.compile_count`).

`bench.py` drives the hot path over `N = 1800` records and prints one JSON line,
`{"elapsed_s": <float>, "n": <int>, "redacted": <int>}`. The buggy baseline runs
in roughly 0.8 s; hoisting the compile out of the loop is several times faster.

Tests in `tests/test_redactor.py`:

* `test_compiles_ruleset_at_most_once` is the **performance oracle** — it counts
  ruleset compilations deterministically (no timing) and fails on the per-record
  implementation (one compile per record), passing once the compile is hoisted
  (one compile per batch).
* `test_redacts_all_secret_and_pii_kinds`,
  `test_preserves_order_count_and_clean_records` and
  `test_empty_batch_and_empty_record` pin the redacted output and edge cases so a
  fast-but-wrong patch (early return, skipped rules, dropped records) cannot earn
  credit.

The fix is to **compile the ruleset once before the loop and reuse the compiled
matchers** for every record — no behavioral change to the redacted output, only
to the algorithmic cost of the pass.
