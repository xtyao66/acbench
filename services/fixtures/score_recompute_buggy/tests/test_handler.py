"""Tests for the risk-scoring ingestion handler.

These are behavioral guards: they pin the *output* of the scoring pass so a
fast-but-wrong optimization cannot earn credit. A correct memoization (caching
the pure risk model per profile key) is invisible to every assertion here --
the scored records, their order, and their values are identical whether or not
the model is cached. A degenerate "fast" patch that skips work, returns an
empty list, drops duplicates, or reorders output fails immediately.

The expected scores are the deterministic outputs of the pure risk model and
are independent of any caching. They are pinned as literals so a patch that
changes *what* is computed (not just *how often*) is caught.
"""

from __future__ import annotations

import unittest

from score_recompute.handler import score_events
from score_recompute.risk_model import score_profile


# Pinned deterministic outputs of the pure risk model. Caching must not change
# these; a wrong-but-fast rewrite will.
_EXPECTED = {
    "actor-0": 2295,
    "actor-1": 2767,
    "actor-2": 714,
    "alpha": 8564,
    "bravo": 1971,
    "charlie": 8760,
    "": 4820,
}


class ScoreEventsTests(unittest.TestCase):
    def test_scores_every_event_with_pinned_values(self) -> None:
        # One record per event, in input order, each carrying the exact
        # deterministic risk score for its profile key. Pinning the literal
        # values means a patch that returns wrong/blank scores (or skips the
        # work) fails here even if it is fast.
        events = [
            {"profile_key": "alpha"},
            {"profile_key": "bravo"},
            {"profile_key": "charlie"},
        ]
        out = score_events(events)
        self.assertEqual(
            out,
            [
                {"profile_key": "alpha", "risk": 8564},
                {"profile_key": "bravo", "risk": 1971},
                {"profile_key": "charlie", "risk": 8760},
            ],
        )

    def test_repeated_keys_get_identical_scores_in_order(self) -> None:
        # The same profile key appearing many times must yield the same score
        # every time, and every event must still produce its own record in the
        # original input order. This is the exact shape memoization optimizes;
        # the observable result must be unchanged. A patch that collapses or
        # de-duplicates repeated events (e.g. returns one record per unique
        # key) fails here.
        events = [
            {"profile_key": "actor-0"},
            {"profile_key": "actor-1"},
            {"profile_key": "actor-0"},
            {"profile_key": "actor-2"},
            {"profile_key": "actor-0"},
            {"profile_key": "actor-1"},
        ]
        out = score_events(events)
        self.assertEqual(
            [r["profile_key"] for r in out],
            ["actor-0", "actor-1", "actor-0", "actor-2", "actor-0", "actor-1"],
        )
        self.assertEqual(
            [r["risk"] for r in out],
            [2295, 2767, 2295, 714, 2295, 2767],
        )
        # Cross-check against the pure model directly: repeated keys are not
        # special-cased into a different value.
        for record in out:
            self.assertEqual(
                record["risk"], _EXPECTED[record["profile_key"]]
            )

    def test_empty_batch_returns_empty(self) -> None:
        # An empty batch yields no records (not None, not a sentinel).
        self.assertEqual(score_events([]), [])

    def test_unknown_and_empty_keys_are_scored_not_skipped(self) -> None:
        # Profile keys the model has no special handling for -- including the
        # empty string -- must still be scored with their deterministic value,
        # never dropped or defaulted to zero. A patch that "fast-paths" unknown
        # keys to a constant fails here.
        events = [
            {"profile_key": ""},
            {"profile_key": "actor-2"},
            {"profile_key": ""},
        ]
        out = score_events(events)
        self.assertEqual(
            out,
            [
                {"profile_key": "", "risk": 4820},
                {"profile_key": "actor-2", "risk": 714},
                {"profile_key": "", "risk": 4820},
            ],
        )

    def test_handler_matches_direct_model_for_a_wide_key_set(self) -> None:
        # Stronger oracle: for a spread of distinct keys, every scored record
        # must equal the pure model's output for that key. This catches any
        # rewrite that changes scores for some keys while leaving the pinned
        # samples above intact.
        keys = [f"actor-{i}" for i in range(40)]
        events = [{"profile_key": k} for k in keys]
        out = score_events(events)
        self.assertEqual([r["profile_key"] for r in out], keys)
        self.assertEqual(
            [r["risk"] for r in out],
            [score_profile(k) for k in keys],
        )


if __name__ == "__main__":
    unittest.main()
