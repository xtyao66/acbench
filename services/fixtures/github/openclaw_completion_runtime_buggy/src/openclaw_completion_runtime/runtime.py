"""Minimal completion-runtime leak reproduction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CompletionProcess:
    session_id: str
    pid: int
    status: str = "running"


class CompletionRuntime:
    """Track spawned completion workers for one localized fixture."""

    def __init__(self) -> None:
        self.active_sessions: set[str] = set()
        self.processes: dict[int, CompletionProcess] = {}

    def start_session(self, session_id: str) -> None:
        self.active_sessions.add(session_id)

    def spawn_completion(self, session_id: str, pid: int) -> None:
        if session_id not in self.active_sessions:
            raise ValueError(f"Unknown session: {session_id}")
        self.processes[pid] = CompletionProcess(session_id=session_id, pid=pid)

    def mark_completion_finished(self, pid: int) -> None:
        self.processes[pid].status = "finished"

    def end_session(self, session_id: str) -> None:
        self.active_sessions.discard(session_id)
        self._cleanup_session_processes(session_id)

    def orphan_process_count(self) -> int:
        return sum(
            1
            for process in self.processes.values()
            if process.session_id not in self.active_sessions
        )

    def _cleanup_session_processes(self, session_id: str) -> None:
        for pid, process in list(self.processes.items()):
            if process.session_id != session_id:
                continue
            if process.status == "running":
                del self.processes[pid]
