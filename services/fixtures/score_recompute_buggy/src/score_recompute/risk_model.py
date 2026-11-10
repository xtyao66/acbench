"""A genuinely expensive, *pure* risk-scoring model.

This stands in for a real per-profile risk computation a fraud/abuse pipeline
might run: a deterministic key-stretching pass (the kind of iterated-hashing
work used to derive a stable fingerprint score). It is intentionally CPU-bound
-- each call performs thousands of SHA-256 rounds -- but it is a *pure function
of its single argument*: the same ``profile_key`` always yields the same score,
so the result is fully memoizable.

The cost is real wall-clock CPU time, not a counter. Scoring the same profile
key twice does the same expensive work twice unless the caller caches it.
"""

from __future__ import annotations

import hashlib

# Number of hash rounds per score. Tuned so a single call costs a small but
# non-trivial slice of CPU time; a batch that re-scores the same handful of
# keys thousands of times spends almost all of its time re-deriving values it
# already computed.
_ROUNDS = 1400


def score_profile(profile_key: str) -> int:
    """Return a deterministic risk score in ``[0, 9999]`` for ``profile_key``.

    Pure and deterministic: the output depends only on ``profile_key``. The
    body performs ``_ROUNDS`` iterations of SHA-256 key stretching -- genuine,
    non-trivial CPU work -- before folding the digest into a bounded score.
    There is no global state and no I/O, so repeated calls with the same key
    are pure waste that a cache could eliminate.
    """

    digest = profile_key.encode("utf-8")
    for _ in range(_ROUNDS):
        digest = hashlib.sha256(digest).digest()
    # Fold the final digest into a stable, bounded integer score.
    acc = 0
    for byte in digest:
        acc = (acc * 31 + byte) & 0xFFFFFFFF
    return acc % 10000
