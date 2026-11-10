"""Internal code runtime models for standalone ACBench."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class NativeCodeInstance:
    """Normalized code-task instance owned by ACBench."""

    instance_id: str
    repo: str
    platform: str
    patch: str
    pred_patch: str
    test_patch: str
    rebuild_cmds: list[str] = field(default_factory=list)
    test_cmds: list[str] = field(default_factory=list)
    print_cmds: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)
    fail_to_pass: list[str] = field(default_factory=list)
    docker_image: str = ""
    log_parser: str = ""
    base_commit: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "NativeCodeInstance":
        """Build a normalized runtime instance from an ACBench or SWE-style payload."""

        return cls(
            instance_id=str(payload.get("instance_id", "")),
            repo=str(payload.get("repo", "")),
            platform=str(payload.get("platform", "linux")),
            patch=str(payload.get("patch", "")),
            pred_patch=str(payload.get("pred_patch", payload.get("patch", ""))),
            test_patch=str(payload.get("test_patch", "")),
            rebuild_cmds=list(payload.get("rebuild_cmds", [])),
            test_cmds=list(payload.get("test_cmds", [])),
            print_cmds=list(payload.get("print_cmds", [])),
            pass_to_pass=list(payload.get("PASS_TO_PASS", [])),
            fail_to_pass=list(payload.get("FAIL_TO_PASS", [])),
            docker_image=str(payload.get("docker_image", "")),
            log_parser=str(payload.get("log_parser", payload.get("parser", ""))),
            base_commit=str(payload.get("base_commit", "")),
        )

    def to_payload(self) -> dict[str, Any]:
        """Convert the internal runtime instance back into a SWE-style payload."""

        return {
            "instance_id": self.instance_id,
            "repo": self.repo,
            "platform": self.platform,
            "patch": self.patch,
            "pred_patch": self.pred_patch,
            "test_patch": self.test_patch,
            "rebuild_cmds": list(self.rebuild_cmds),
            "test_cmds": list(self.test_cmds),
            "print_cmds": list(self.print_cmds),
            "PASS_TO_PASS": list(self.pass_to_pass),
            "FAIL_TO_PASS": list(self.fail_to_pass),
            "docker_image": self.docker_image,
            "log_parser": self.log_parser,
            "base_commit": self.base_commit,
        }


@dataclass(slots=True)
class CodeRunRequest:
    """Execution request for the future standalone ACBench code runtime."""

    instance: NativeCodeInstance
    output_dir: Path
    keep_workspace: bool = True


@dataclass(slots=True)
class CodeRunOutcome:
    """Normalized output shape for the future standalone ACBench code runtime."""

    resolved: bool
    pass_to_pass_success: list[str] = field(default_factory=list)
    pass_to_pass_failure: list[str] = field(default_factory=list)
    fail_to_pass_success: list[str] = field(default_factory=list)
    fail_to_pass_failure: list[str] = field(default_factory=list)
    logs: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def to_report(self, instance_id: str) -> dict[str, Any]:
        """Convert the runtime outcome into the current SWE-style report shape."""

        return {
            "instance_id": instance_id,
            "resolved": self.resolved,
            "PASS_TO_PASS": {
                "success": list(self.pass_to_pass_success),
                "failure": list(self.pass_to_pass_failure),
            },
            "FAIL_TO_PASS": {
                "success": list(self.fail_to_pass_success),
                "failure": list(self.fail_to_pass_failure),
            },
            "logs": dict(self.logs),
            "details": dict(self.details),
        }


def workspace_dir(output_dir: str | Path, instance_id: str) -> Path:
    """Return the future standalone workspace path for one code-task instance."""

    base = Path(output_dir)
    return base / instance_id / "workspace"
