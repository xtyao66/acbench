"""Feature rollout helpers for the local routing fixture."""

from __future__ import annotations

import hashlib


def stable_bucket(user_id: str) -> int:
    """Map one user id into a stable 0-99 rollout bucket."""

    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def choose_variant(
    user_id: str,
    *,
    rollout_percent: int,
    allowlist: set[str] | None = None,
    denylist: set[str] | None = None,
) -> str:
    """Choose whether the user sees the new variant or the control variant."""

    allowlist = set(allowlist or [])
    denylist = set(denylist or [])

    if user_id in allowlist:
        return "new"

    bucket = stable_bucket(user_id)
    if bucket < rollout_percent:
        return "new"

    if user_id in denylist:
        return "control"

    return "control"
