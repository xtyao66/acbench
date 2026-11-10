"""Maintenance window helpers for the local scheduler fixture."""

from __future__ import annotations

from datetime import time


def parse_clock(value: str) -> time:
    """Parse an HH:MM clock string into a ``time`` object."""

    hours, minutes = value.split(":", maxsplit=1)
    return time(hour=int(hours), minute=int(minutes))


def is_time_in_window(moment: time, start: time, end: time) -> bool:
    """Return whether the moment falls inside the maintenance window."""

    if start <= end:
        return start <= moment < end
    return start <= moment < end


def is_clock_string_in_window(
    clock_value: str,
    start_value: str,
    end_value: str,
) -> bool:
    """Convenience wrapper around string-based maintenance window checks."""

    return is_time_in_window(
        parse_clock(clock_value),
        parse_clock(start_value),
        parse_clock(end_value),
    )
