# parse-once-cache-buggy

Local ACBench performance fixture for the `parse_once_cache` archetype.

The request-routing resolver in `src/route_config/resolver.py` answers
`resolve(path)` for each inbound request by looking up the route's backend pool
in a routing table. That routing table arrives as a serialized JSON config
document (`src/route_config/config_blob.py`, `RAW_CONFIG`): plain JSON **text**
that must be deserialized into Python objects before any route can be read out
of it. Because the resolver calls `json.loads(self._raw_config)` **on every
`resolve` call**, it re-parses the entire (hundreds-of-KB) document once per
request. The parsing cost is paid `N` times for a stream of `N` requests and
dominates CPU time at scale.

`RouteResolver` is instrumented: it **counts every time it deserializes the
config document** in `parse_count`. The counting regression test in
`tests/test_resolver.py` drives the resolver over many lookups and asserts the
document is parsed a small constant number of times, not once per request. It
fails on the parse-per-call implementation (`parse_count == N`) and passes once
the parsed config is cached (`parse_count <= 2`). The behavioral tests pin the
resolved backends — known routes, the default fallback for unknown routes, and
stable repeated/mixed lookups — so a fast-but-wrong patch cannot earn credit.

The fix is to **parse the config document once and cache the parsed result**
(parse in `__init__`, or memoize on first use) and serve every `resolve` lookup
from the cached Python objects — no behavioral change to the resolved backends,
only to the per-request parsing cost.

## bench.py

`bench.py` constructs one long-lived resolver and resolves `N = 4000` requests
against it, printing one JSON line `{"elapsed_s": <float>, "n": <int>,
"checksum": <int>}`. The buggy baseline re-parses the document 4000 times; the
parse-once fix parses it once. Run it with:

```
PYTHONPATH=src python bench.py
```
