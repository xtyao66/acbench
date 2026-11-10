"""Tests for the leaderboard ranking handler.

``test_sorts_scoreboard_at_most_once`` is the performance oracle: it counts how
many times the scoreboard is sorted (no wall-clock timing) and fails on the
implementation that re-sorts inside the per-player loop. The correctness tests
pin the ranked output so the sort-once rewrite cannot earn credit by changing
behavior.
"""

from __future__ import annotations

import unittest

from leaderboard_rank.handler import rank_players
from leaderboard_rank.sorter import SortMeter


def _make_scores() -> dict[str, int]:
    return {
        "ada": 90,
        "lin": 90,
        "mei": 75,
        "ben": 60,
        "cy": 110,
    }


def _make_queries() -> list[str]:
    return ["mei", "cy", "lin", "ada", "ghost", "ben"]


class LeaderboardRankTests(unittest.TestCase):
    def test_sorts_scoreboard_at_most_once(self) -> None:
        meter = SortMeter()
        rank_players(_make_queries(), _make_scores(), meter)
        # Performance oracle: regardless of how many players are queried, the
        # scoreboard only needs to be ranked once per request.
        self.assertLessEqual(meter.sort_count, 1)

    def test_returns_one_result_per_query_in_order(self) -> None:
        meter = SortMeter()
        results = rank_players(_make_queries(), _make_scores(), meter)
        self.assertEqual(
            [r["player_id"] for r in results],
            ["mei", "cy", "lin", "ada", "ghost", "ben"],
        )

    def test_ranks_scores_with_tie_break_and_unknown_fallback(self) -> None:
        meter = SortMeter()
        results = rank_players(_make_queries(), _make_scores(), meter)
        by_player = {r["player_id"]: r for r in results}
        # Ranking: cy(110)=1, ada(90)=2, lin(90)=3 (tie broken by id),
        # mei(75)=4, ben(60)=5.
        self.assertEqual((by_player["cy"]["rank"], by_player["cy"]["score"]), (1, 110))
        self.assertEqual((by_player["ada"]["rank"], by_player["ada"]["score"]), (2, 90))
        self.assertEqual((by_player["lin"]["rank"], by_player["lin"]["score"]), (3, 90))
        self.assertEqual((by_player["mei"]["rank"], by_player["mei"]["score"]), (4, 75))
        self.assertEqual((by_player["ben"]["rank"], by_player["ben"]["score"]), (5, 60))
        # Unknown player falls back to rank 0 / score 0.
        self.assertEqual((by_player["ghost"]["rank"], by_player["ghost"]["score"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
