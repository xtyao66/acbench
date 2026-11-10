"""Minimal active-run listener crash reproduction."""

from __future__ import annotations


class AgentRuntime:
    """Track one active run and process listener events."""

    def __init__(self) -> None:
        self.active_run_id: str | None = None
        self.processed_events: list[tuple[str, str]] = []
        self.warnings: list[str] = []

    def start_run(self, run_id: str) -> None:
        self.active_run_id = run_id

    def finish_run(self) -> None:
        self.active_run_id = None

    def process_listener_event(self, channel: str, payload: str) -> str:
        if self.active_run_id is None:
            raise RuntimeError("Agent listener invoked outside active run")
        self.processed_events.append((channel, payload))
        return "processed"
