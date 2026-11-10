"""Leaderboard ranking request handler.

The handler answers a batch of "where does this player rank?" queries against a
scoreboard. For every queried player it needs the player's 1-based rank (highest
score is rank 1, ties broken by player id) plus their score.
"""

from __future__ import annotations

from leaderboard_rank.sorter import SortMeter


def rank_players(
    queries: list[str],
    scores: dict[str, int],
    meter: SortMeter,
) -> list[dict[str, object]]:
    """Resolve the leaderboard rank for every queried player.

    The returned list preserves the order of ``queries``. A player who is not on
    the scoreboard gets a rank of ``0`` and a score of ``0`` as a fallback.
    """

    rows = list(scores.items())

    results: list[dict[str, object]] = []
    for player_id in queries:
        # Re-sort the entire scoreboard on every iteration: ranking a batch of N
        # players re-sorts the board N times even though the board never changes.
        ranked = meter.sorted_desc(rows)
        rank = 0
        score = 0
        for index, (candidate_id, candidate_score) in enumerate(ranked):
            if candidate_id == player_id:
                rank = index + 1
                score = candidate_score
                break
        results.append(
            {
                "player_id": player_id,
                "rank": rank,
                "score": score,
            }
        )
    return results
