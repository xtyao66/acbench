# audit-search-buggy

Local ACBench performance fixture for the `eager_overfetch` archetype.

The audit-log search handler in `src/audit_search/search.py` answers a scoped
query (all events for one tenant at or above a severity threshold) by pulling
**every row in the table** out of the store and filtering them in Python. When
the table holds millions of rows but a tenant matches only a handful, the
handler reads orders of magnitude more rows than it returns, which is what blows
the query latency and store I/O budget under load.

`src/audit_search/store.py` is a tiny in-repo fake event store that **records
how many rows it hands back** (`rows_returned`) and how many distinct scans it
served (`scan_count`). The full-table `scan_all()` returns — and counts — every
row in the table; the predicate-pushed `query(tenant_id, min_severity)` returns
and counts only the rows that actually match.

The counting regression test in `tests/test_search.py` loads a table where only
a small subset of rows match the scoped query and asserts the handler pulled
back **no more rows than actually match** (`rows_returned <= matching rows`). It
fails on the fetch-everything-then-filter implementation (which returns the
whole table) and passes once the predicate is pushed into the store query.

The fix is to push the tenant + severity predicate down into the store's
`query(...)` call so the store only materializes matching rows — no behavioral
change to the returned results, only to how many rows are scanned out of the
store.
