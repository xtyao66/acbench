"""Risk-scoring ingestion handler.

The abuse-detection worker receives a batch of inbound events. Each event names
a ``profile_key`` identifying the actor it came from. The worker must attach a
risk score to every event by running the (expensive, pure) risk model on the
event's profile key, then return one scored record per input event in input
order.

In a real stream the same actors appear over and over, so the same handful of
profile keys repeat across thousands of events. The risk model is a *pure
function of the profile key*, yet this handler invokes it once per event -- so
it re-derives the identical score for a repeated key again and again, which is
where the CPU time goes.
"""

from __future__ import annotations

from score_recompute.risk_model import score_profile


def score_events(events: list[dict[str, str]]) -> list[dict[str, object]]:
    """Return one scored record per event, in input order.

    Each record echoes the event's ``profile_key`` and attaches the risk score
    produced by the pure risk model for that key.
    """

    scored: list[dict[str, object]] = []
    for event in events:
        profile_key = event["profile_key"]
        # The expensive, *pure* risk model is recomputed for every event, even
        # when many events repeat the same profile key: N full computations for
        # a batch of N events regardless of how few distinct keys there are.
        risk = score_profile(profile_key)
        scored.append({"profile_key": profile_key, "risk": risk})
    return scored
