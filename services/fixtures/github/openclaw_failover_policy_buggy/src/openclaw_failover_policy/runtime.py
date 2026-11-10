"""Minimal failover-policy reproduction."""

from __future__ import annotations


def decide_main_lane_action(
    consecutive_transport_errors: int,
    error_type: str,
    threshold: int = 3,
) -> str:
    """Decide whether the main lane should retry or fail over."""

    if error_type != "transport":
        return "surface_error"
    if consecutive_transport_errors > threshold:
        return "fallback"
    return "retry"
