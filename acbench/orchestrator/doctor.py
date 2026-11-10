"""Environment diagnostics for standalone ACBench."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

from acbench.paths import repo_root


def _module_available(module_name: str) -> bool:
    """Return whether a Python module can be imported."""

    return importlib.util.find_spec(module_name) is not None


def _command_available(command_name: str) -> bool:
    """Return whether a shell command is available on PATH."""

    return shutil.which(command_name) is not None


def _resolve_command(command_name: str, repo_root: Path | None = None) -> str | None:
    """Resolve a command from PATH or known bundled tool locations."""

    resolved = shutil.which(command_name)
    if resolved:
        return resolved

    if repo_root is None:
        return None

    candidates = [
        repo_root / "tools" / "bin" / command_name,
        repo_root / "tools" / "bin" / f"{command_name}.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


@dataclass(slots=True)
class ToolCheck:
    """Single package or command check result."""

    name: str
    available: bool


@dataclass(slots=True)
class ProjectDoctorReport:
    """Environment diagnostics for one backend project."""

    name: str
    repo_root: str
    python_version: str
    declared_dependencies: list[str] = field(default_factory=list)
    required_modules: list[ToolCheck] = field(default_factory=list)
    recommended_commands: list[ToolCheck] = field(default_factory=list)
    extra_checks: dict[str, object] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)

    @property
    def import_ready(self) -> bool:
        return all(check.available for check in self.required_modules)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "repo_root": self.repo_root,
            "python_version": self.python_version,
            "declared_dependencies": list(self.declared_dependencies),
            "required_modules": [asdict(item) for item in self.required_modules],
            "recommended_commands": [asdict(item) for item in self.recommended_commands],
            "extra_checks": dict(self.extra_checks),
            "next_actions": list(self.next_actions),
            "import_ready": self.import_ready,
        }


def _load_dependencies(pyproject_path: Path) -> list[str]:
    """Load string dependencies from a pyproject file when possible."""

    if not pyproject_path.exists():
        return []
    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)

    if "project" in data and "dependencies" in data["project"]:
        return list(data["project"]["dependencies"])

    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    return [name for name in poetry_deps.keys() if name != "python"]


def _normalize_import_name(requirement_name: str) -> str:
    """Map package names to import module names conservatively."""

    token = requirement_name.split(">=")[0].split("==")[0].split("^")[0].split("<")[0]
    token = token.split("[")[0].strip()
    return token.replace("-", "_")


def _run_command(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = 10,
) -> tuple[bool, str]:
    """Run a command and return a success flag and trimmed output."""

    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as exc:
        return False, str(exc)

    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output.strip()


def inspect_acbench_code_backend() -> ProjectDoctorReport:
    """Collect diagnostics for the internal ACBench standalone code backend."""

    git_cmd = _resolve_command("git")
    commands = [
        ToolCheck(name="git", available=git_cmd is not None),
    ]
    report = ProjectDoctorReport(
        name="acbench-code",
        repo_root=str(repo_root()),
        python_version=sys.version.split()[0],
        declared_dependencies=[],
        required_modules=[],
        recommended_commands=commands,
        extra_checks={
            "backend_type": "standalone-local-code",
            "git_available": git_cmd is not None,
        },
    )
    report.next_actions = build_next_actions(report)
    return report


def build_next_actions(report: ProjectDoctorReport) -> list[str]:
    """Generate actionable next steps from a project doctor report."""

    actions: list[str] = []
    missing_modules = [item.name for item in report.required_modules if not item.available]
    missing_commands = [item.name for item in report.recommended_commands if not item.available]

    if report.name == "acbench-code":
        if "git" in missing_commands:
            actions.append("Install Git to enable patch diff capture for the standalone ACBench code backend.")
    return actions


def build_readiness_bundle() -> dict:
    """Build a standalone environment readiness report."""

    acbench_code = inspect_acbench_code_backend()
    return {
        "acbench_code": acbench_code.to_dict(),
        "summary": {
            "acbench_code_ready": True,
        },
    }
