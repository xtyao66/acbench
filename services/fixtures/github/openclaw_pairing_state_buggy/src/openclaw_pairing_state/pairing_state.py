"""Small pairing-state reproduction derived from an OpenClaw issue."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _state_path(base_dir: str | Path, filename: str) -> Path:
    return Path(base_dir) / filename


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_state(base_dir: str | Path) -> dict[str, Any]:
    """Load pending and paired device state from disk."""

    pending = _read_json(_state_path(base_dir, "pending.json"))
    paired = _read_json(_state_path(base_dir, "paired.json"))
    return {
        "pending_by_id": pending if pending is not None else {},
        "paired_by_device_id": paired if paired is not None else {},
    }


def persist_state(base_dir: str | Path, state: dict[str, Any]) -> None:
    """Persist pairing state back to disk."""

    _write_json(_state_path(base_dir, "pending.json"), state["pending_by_id"])
    _write_json(_state_path(base_dir, "paired.json"), state["paired_by_device_id"])


def request_device_pairing(
    base_dir: str | Path,
    request_id: str,
    device_id: str,
    *,
    silent: bool = True,
) -> dict[str, Any]:
    """Record one pending pairing request."""

    state = load_state(base_dir)
    record = {
        "request_id": request_id,
        "device_id": device_id,
        "silent": silent,
        "status": "pending",
    }
    pending = state["pending_by_id"]
    if isinstance(pending, list):
        pending.append(record)
    else:
        pending[request_id] = record
    persist_state(base_dir, state)
    return record


def approve_device_pairing(base_dir: str | Path, request_id: str) -> dict[str, Any] | None:
    """Approve one pending request if it can be found."""

    state = load_state(base_dir)
    pending = state["pending_by_id"]
    if not isinstance(pending, dict):
        return None

    record = pending.pop(request_id, None)
    if record is None:
        return None

    paired = state["paired_by_device_id"]
    if not isinstance(paired, dict):
        return None

    approval = {
        "request_id": request_id,
        "device_id": record["device_id"],
        "status": "approved",
    }
    paired[record["device_id"]] = approval
    persist_state(base_dir, state)
    return approval
