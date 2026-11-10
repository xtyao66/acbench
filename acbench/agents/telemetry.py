"""Shared timing helpers for benchmark-backed agent calls."""

from __future__ import annotations

from time import perf_counter
from typing import Any, Callable


def timed_call(
    label: str,
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> tuple[Any, dict[str, Any]]:
    """Execute one callable and capture its wall-clock duration."""

    started = perf_counter()
    result = func(*args, **kwargs)
    duration = perf_counter() - started
    return result, {
        "label": label,
        "duration_seconds": round(duration, 6),
    }


def summarize_call_records(
    records: list[dict[str, Any]],
    *,
    wall_time_seconds: float,
) -> dict[str, Any]:
    """Summarize one list of timed agent calls into stable telemetry."""

    durations = [
        round(float(record.get("duration_seconds", 0.0)), 6)
        for record in records
    ]
    total_answer_seconds = round(sum(durations), 6)
    answer_count = len(durations)
    average_answer_seconds = round(
        total_answer_seconds / answer_count,
        6,
    ) if answer_count else 0.0
    return {
        "answer_count": answer_count,
        "answer_durations_seconds": durations,
        "total_answer_seconds": total_answer_seconds,
        "average_answer_seconds": average_answer_seconds,
        "wall_time_seconds": round(wall_time_seconds, 6),
        "answer_labels": [str(record.get("label", "")) for record in records],
    }
