# notify-fanout-buggy

Local ACBench performance fixture for the `n_plus_one_query` archetype.

The notification fan-out handler in `src/notify_fanout/handler.py` resolves the
recipient profile for every event by issuing **one datastore lookup per event**
inside a loop. For a batch of `N` events that is `N` round-trips to the profile
store, which dominates p99 latency under load.

`src/notify_fanout/store.py` is a tiny in-repo fake datastore that **counts every
query** it serves (both single-key `get` and batched `get_many`). The counting
regression test in `tests/test_handler.py` drives the handler over a batch of
events and asserts the handler made **at most one** datastore query. It fails on
the per-event-loop implementation (N queries) and passes once the lookups are
batched into a single `get_many`.

The fix is to collect the distinct recipient ids first and resolve them with a
single batched lookup before building the messages — no behavioral change to the
returned messages, only to the number of datastore round-trips.
