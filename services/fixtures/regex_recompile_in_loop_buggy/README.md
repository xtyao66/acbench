# regex-recompile-in-loop-buggy

Local ACBench performance fixture for the `regex_recompile_in_loop` archetype.

The log-scrubber in `src/log_scrubber/scrubber.py` redacts secrets from a batch
of log lines. It **re-compiles the same redaction regex on every line** inside
the per-line loop. For a batch of `N` lines that is `N` calls to the regex
compiler, even though the pattern never changes — wasted CPU that dominates the
scrub path under load.

`src/log_scrubber/regexlab.py` is a tiny in-repo regex compiler facade that
**counts every compile** it performs (`compile_count`). The counting regression
test in `tests/test_scrubber.py` drives the scrubber over a batch of lines and
asserts the scrubber compiled the pattern **at most once**. It fails on the
per-line implementation (N compiles) and passes once the compile is hoisted out
of the loop and the cached pattern is reused.

The fix is to compile the redaction pattern a single time before the loop and
reuse the compiled pattern for every line — no behavioral change to the
redacted output, only to the number of compile invocations.
