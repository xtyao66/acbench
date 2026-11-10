# config-reload-buggy

Local ACBench performance fixture for the `repeated_io_read` archetype.

The pricing-quote handler in `src/config_reload/pricer.py` resolves the active
pricing rules by **reading and parsing the pricing-rules config file from disk on
every quote** it serves. For a batch of `N` quotes that is `N` file reads and `N`
JSON parses of the same unchanged config, which dominates p99 latency under load.

`src/config_reload/config_source.py` is a tiny in-repo config source that **counts
every time the config file is read and parsed** (`load()` increments
`read_count`). The counting regression test in `tests/test_pricer.py` drives the
handler over a batch of quotes and asserts the handler read/parsed the config
**at most once**. It fails on the read-per-quote implementation (N reads) and
passes once the config is loaded once and reused.

The fix is to load and parse the config a single time up front and reuse the
parsed rules for every quote in the batch — no behavioral change to the returned
quotes, only to the number of file reads / parses.
