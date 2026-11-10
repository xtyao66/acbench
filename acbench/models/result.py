"""Result models for the ACBench."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_safe(value: Any) -> Any:
    """Recursively normalize values into JSON-serializable primitives."""

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass(slots=True)
class RunArtifacts:
    """Paths to run artifacts produced by the benchmark."""

    result_path: str = ""
    summary_path: str = ""
    scenario_path: str = ""
    diagnostics_path: str = ""
    trace_path: str = ""
    patch_path: str = ""
    build_log_path: str = ""
    test_log_path: str = ""
    telemetry_summary_path: str = ""


@dataclass(slots=True)
class ExecutorResult:
    """Normalized executor output."""

    backend: str
    success: bool = False
    detected: bool = False
    localized: bool = False
    repaired: bool = False
    build_success: bool = False
    test_success: bool = False
    deploy_success: bool = False
    pass_to_pass_success: list[str] = field(default_factory=list)
    pass_to_pass_failure: list[str] = field(default_factory=list)
    fail_to_pass_success: list[str] = field(default_factory=list)
    fail_to_pass_failure: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    logs: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BenchmarkResult:
    """Unified top-level benchmark result."""

    scenario_id: str
    title: str
    mode: str
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str = ""
    status: str = "pending"
    ops_result: ExecutorResult | None = None
    code_result: ExecutorResult | None = None
    unified_metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: RunArtifacts = field(default_factory=RunArtifacts)
    notes: list[str] = field(default_factory=list)

    def finalize(self, status: str) -> None:
        """Finalize the result status and timestamp."""

        self.status = status
        self.finished_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    def write_json(self, output_path: str | Path) -> Path:
        """Persist the benchmark result as JSON."""

        import json

        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2)
        return target
