# group-by-dict-buggy

Local ACBench performance fixture for the `group_by_dict` archetype.

The per-tenant metrics roll-up in `src/group_metrics/aggregator.py` groups a flat
batch of metering records by `tenant_id`. To find the group a record belongs to,
it performs a **linear "find the group" scan** over the list of groups built so
far. Because that list grows as new tenants appear, rolling up a batch of `N`
records across `G` distinct tenants costs roughly `O(N*G)` key comparisons — and
when the tenant count grows with the batch (one record per API call across every
tenant on the platform), that is `O(N^2)`: doubling the batch roughly quadruples
the work and the roll-up dominates the nightly billing job's CPU time.

`bench.py` drives the hot path at a scale where this cost dominates measurement
noise and prints one JSON line `{"elapsed_s":..,"n":..,"groups":..}`.

The fix is to index the groups by key in a `dict` (e.g. `collections.defaultdict`)
so finding a record's group is an `O(1)` hash lookup instead of a linear scan —
turning the roll-up from `O(N*G)` into `O(N)` with **no behavioral change** to
the emitted groups, their first-seen order, counts, or summed units. The
behavioral tests in `tests/test_aggregator.py` pin that output so a fast-but-wrong
rewrite cannot earn credit.
