# leaderboard-rank-buggy

Local ACBench performance fixture for the `repeated_sort_in_loop` archetype.

The leaderboard ranking handler in `src/leaderboard_rank/handler.py` answers a
batch of "where does this player rank?" queries. It re-sorts the **entire
scoreboard inside the per-player loop**, so a batch of `N` queries sorts the same
unchanging board `N` times. The sort cost dominates request latency and CPU as
the batch and board grow.

`src/leaderboard_rank/sorter.py` is a tiny in-repo sort instrument that **counts
every full re-sort** it performs (`SortMeter.sorted_desc`). The counting
regression test in `tests/test_handler.py` drives the handler over a batch of
queries and asserts the scoreboard was sorted **at most once**. It fails on the
sort-in-loop implementation (N sorts) and passes once the sort is hoisted out of
the loop.

The fix is to rank the scoreboard a single time before the loop and reuse the
ranked order (or a precomputed rank lookup) for every queried player — no
behavioral change to the returned ranks, only to the number of sorts performed.
