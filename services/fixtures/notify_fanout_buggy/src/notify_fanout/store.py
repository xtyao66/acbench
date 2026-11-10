"""Tiny in-repo fake profile datastore that counts queries.

This stands in for an external key-value / row store. Every call that reaches
the backend increments ``query_count`` so a regression test can assert how many
round-trips a handler performs, deterministically and without any wall-clock
timing.
"""

from __future__ import annotations


class ProfileStore:
    """A fake recipient-profile store that counts each query it serves."""

    def __init__(self, profiles: dict[str, dict[str, str]]) -> None:
        self._profiles = dict(profiles)
        # Number of datastore round-trips served. Both ``get`` and
        # ``get_many`` count as exactly one query each.
        self.query_count = 0

    def get(self, recipient_id: str) -> dict[str, str] | None:
        """Resolve a single recipient profile (one round-trip)."""

        self.query_count += 1
        return self._profiles.get(recipient_id)

    def get_many(self, recipient_ids: list[str]) -> dict[str, dict[str, str]]:
        """Resolve many recipient profiles in a single batched round-trip."""

        self.query_count += 1
        return {
            recipient_id: self._profiles[recipient_id]
            for recipient_id in recipient_ids
            if recipient_id in self._profiles
        }
