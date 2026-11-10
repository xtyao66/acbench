"""Standalone execution primitives for the future internal ACBench code backend."""

from __future__ import annotations

import os
from pathlib import Path
import posixpath
import re
import shlex
import shutil
import signal
import subprocess
import sys

# Per-command wall-clock budget when the caller does not pass one; matches the
# ``constraints.max_runtime_minutes`` default (30 minutes).
DEFAULT_COMMAND_TIMEOUT_SECONDS = 30 * 60
# Exit code recorded for a command killed on timeout (GNU ``timeout`` convention).
TIMEOUT_EXIT_CODE = 124

_DEV_NULL = "/dev/null"
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
# ``python`` as the first real command, optionally behind PowerShell
# ``$env:NAME='value';`` prefixes (which PowerShell itself still evaluates).
_POWERSHELL_PYTHON = re.compile(
    r"^((?:\$env:[A-Za-z_][A-Za-z0-9_]*=(['\"]).*?\2\s*;\s*)*)python(?=\s|$)"
)
# POSIX ``NAME=value`` prefix with a literal (unquoted or single-quoted) value.
_POSIX_ENV_PREFIX = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=('[^']*'|[^\s'\"$`]+)\s+(.*)$")


def prepare_workspace(source_repo: str | Path, run_dir: str | Path) -> Path:
    """Copy a source repository into a run-local workspace."""

    repo_path = Path(source_repo)
    if not repo_path.is_absolute():
        repo_path = Path.cwd() / repo_path
    repo_path = repo_path.resolve()

    workspace_path = Path(run_dir) / "workspace"
    shutil.copytree(repo_path, workspace_path)
    return workspace_path


def run_commands(
    commands: list[str],
    repo_path: str | Path,
    timeout: float | None = None,
) -> tuple[bool, str]:
    """Run commands in one repository and aggregate logs.

    ``timeout`` is the per-command budget in seconds (default
    ``DEFAULT_COMMAND_TIMEOUT_SECONDS``); a command that exceeds it is killed
    and counts as a failure.
    """

    if not commands:
        return True, ""

    target = Path(repo_path)
    chunks: list[str] = []
    overall_success = True
    for command in commands:
        result = run_single_command(command, target, timeout=timeout)
        chunks.append(
            f"$ {command}\n{result.stdout}{result.stderr}\nexit_code={result.returncode}\n"
        )
        if result.returncode != 0:
            overall_success = False
            break
    return overall_success, "\n".join(chunks)


def run_single_command(
    command: str,
    repo_path: Path,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one command in the repository path.

    The command is killed together with every process it started once it runs
    longer than ``timeout`` seconds; the result then carries
    ``TIMEOUT_EXIT_CODE`` and a note on stderr instead of hanging the run.
    """

    normalized_command, env_overrides = normalize_command(command)
    env = os.environ.copy()
    env.update(env_overrides)
    if timeout is None:
        timeout = DEFAULT_COMMAND_TIMEOUT_SECONDS

    if os.name == "nt":
        args: str | list[str] = ["powershell", "-Command", normalized_command]
        extra: dict = {}
    else:
        # A new session makes the shell the leader of a process group, so a
        # timeout can kill the test processes it spawned, not just the shell.
        args = normalized_command
        extra = {"shell": True, "start_new_session": True}

    with subprocess.Popen(
        args,
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **extra,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                # An escaped grandchild still holds the pipes; give up on output.
                stdout, stderr = "", ""
            stderr = (
                f"{stderr}\n[acbench] command timed out after {timeout:g}s; "
                "process tree killed\n"
            )
            return subprocess.CompletedProcess(args, TIMEOUT_EXIT_CODE, stdout, stderr)
        except BaseException:
            # Ctrl-C and other aborts: the new session hides the children from
            # the terminal's SIGINT, so stop them here before propagating.
            _kill_process_tree(process)
            raise
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def _kill_process_tree(process: subprocess.Popen) -> None:
    """Kill a timed-out command and every process it started."""

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        process.kill()
    except OSError:
        pass


def normalize_command(command: str) -> tuple[str, dict[str, str]]:
    """Normalize cross-shell command syntax for local fixture execution."""

    normalized = command.strip()
    env_overrides: dict[str, str] = {}

    if os.name != "nt":
        normalized, env_overrides = _extract_powershell_env_assignments(normalized)
        if normalized.startswith("Write-Output "):
            normalized = f"echo {normalized[len('Write-Output '):]}"
        if normalized == "python" or normalized.startswith("python "):
            normalized = f"{shlex.quote(sys.executable)}{normalized[6:]}"
        return normalized, env_overrides

    # PowerShell does not understand POSIX ``NAME=value cmd`` prefixes.
    normalized, env_overrides = _extract_posix_env_assignments(normalized)
    # Rewrite ``python`` to this interpreter even behind ``$env:`` prefixes, so
    # test commands run the same Python as rebuild commands (as on POSIX).
    match = _POWERSHELL_PYTHON.match(normalized)
    if match:
        executable = sys.executable.replace('"', '`"')
        normalized = f'{match.group(1)}& "{executable}"{normalized[match.end():]}'

    return normalized, env_overrides


def _extract_posix_env_assignments(command: str) -> tuple[str, dict[str, str]]:
    """Translate literal POSIX ``NAME=value`` command prefixes into env overrides."""

    env_overrides: dict[str, str] = {}
    remaining = command
    while True:
        match = _POSIX_ENV_PREFIX.match(remaining)
        if not match:
            return remaining, env_overrides
        env_overrides[match.group(1)] = match.group(2).strip("'")
        remaining = match.group(3).lstrip()


def _extract_powershell_env_assignments(command: str) -> tuple[str, dict[str, str]]:
    """Translate simple PowerShell ``$env:NAME='value';`` prefixes into env overrides."""

    env_overrides: dict[str, str] = {}
    remaining = command
    pattern = re.compile(r"^\$env:([A-Za-z_][A-Za-z0-9_]*)=(['\"])(.*?)\2\s*;\s*(.*)$")

    while True:
        match = pattern.match(remaining)
        if not match:
            return remaining, env_overrides
        env_overrides[match.group(1)] = match.group(3)
        remaining = match.group(4).lstrip()


def capture_git_diff(repo_path: str | Path) -> str:
    """Capture a git diff for one repository when possible."""

    target = Path(repo_path)
    if not shutil.which("git"):
        return ""
    # Only diff a workspace that is itself a repository root. A plain copied
    # fixture nested inside another checkout (e.g. runs/ under the benchmark
    # repo) would otherwise report that outer repository's unrelated changes.
    toplevel = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=target,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        if toplevel.returncode != 0 or not Path(toplevel.stdout.strip()).samefile(target):
            return ""
    except OSError:
        return ""
    result = subprocess.run(
        ["git", "--no-pager", "diff", "HEAD", "--text"],
        cwd=target,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def apply_patch(repo_path: str | Path, patch_file: str | Path) -> tuple[bool, str]:
    """Apply a unified diff patch to a repository."""

    target = Path(repo_path)
    patch_path = Path(patch_file)
    if not patch_path.exists():
        return False, f"Patch file does not exist: {patch_path}\n"
    if (target / ".git").exists() and shutil.which("git"):
        result = subprocess.run(
            [
                "git",
                "apply",
                "--reject",
                "--whitespace=nowarn",
                str(patch_path),
            ],
            cwd=target,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = (
            f"$ git apply --reject --whitespace=nowarn {patch_path}\n"
            f"{result.stdout}{result.stderr}\nexit_code={result.returncode}\n"
        )
        return result.returncode == 0, output
    return apply_patch_without_git(target, patch_path)


def apply_patch_without_git(repo_path: Path, patch_file: Path) -> tuple[bool, str]:
    """Apply a small unified diff patch without requiring git metadata."""

    patch_text = patch_file.read_text(encoding="utf-8")
    sections = _split_patch_sections(patch_text)
    applied_files: list[str] = []

    for section in sections:
        section = section.strip()
        if not section:
            continue
        lines = section.splitlines()
        if len(lines) < 3:
            return False, f"Unsupported patch section in {patch_file}\n"
        old_path, new_path, renamed, remaining_lines = _extract_patch_target(
            lines, patch_file
        )
        if not old_path:
            return False, f"Unsupported patch header in {patch_file}\n"
        creating = old_path == _DEV_NULL
        deleting = new_path == _DEV_NULL
        source_rel = new_path if creating else old_path
        # Only an explicit rename moves the file; otherwise the old path is
        # patched in place, as before (e.g. ``diff -u foo.py foo.py.new``).
        dest_rel = new_path if renamed else source_rel
        source_file = _workspace_file(repo_path, source_rel)
        dest_file = _workspace_file(repo_path, dest_rel)
        if source_file is None or dest_file is None:
            return False, f"Refusing to patch a path outside the workspace: {source_rel}\n"
        if creating and source_file.exists():
            return False, f"Target file already exists for new-file patch: {source_file}\n"
        if not creating and not source_file.exists():
            return False, f"Target file does not exist for patch: {source_file}\n"

        # Keep the file's own line endings and final-newline state.
        raw = "" if creating else source_file.read_bytes().decode("utf-8")
        eol = "\r\n" if "\r\n" in raw else "\n"
        original = raw.splitlines()
        final_newline = raw.endswith(("\n", "\r")) or not original
        stated = _patched_final_newline(remaining_lines)
        if stated is not None:
            final_newline = stated

        hunks = parse_unified_hunks(remaining_lines, source_file)
        if isinstance(hunks, str):
            return False, hunks
        patched = list(original)
        search_start = 0
        line_offset = 0
        for source_chunk, target_chunk, old_start in hunks:
            if source_chunk:
                # Anchor on the declared line (shifted by earlier hunks) so repeated
                # context patches the intended occurrence, not the first one.
                anchor = old_start - 1 + line_offset if old_start > 0 else None
                match_index = find_subsequence(patched, source_chunk, search_start, anchor)
                if match_index < 0:
                    return False, f"Context mismatch while patching {source_file}\n"
            else:
                # Pure addition (no context/deletion): insert at the hunk's declared
                # start line, shifted by prior hunks' net line changes — NOT blindly
                # at search_start (which would dump it at the top of the file).
                match_index = max(0, min(len(patched), old_start + line_offset))
            patched = (
                patched[:match_index]
                + target_chunk
                + patched[match_index + len(source_chunk) :]
            )
            search_start = match_index + len(target_chunk)
            line_offset += len(target_chunk) - len(source_chunk)

        if deleting:
            if patched and hunks:
                return False, f"Context mismatch while deleting {source_file}\n"
            source_file.unlink()
            applied_files.append(str(source_file))
            continue
        text = eol.join(patched) + (eol if patched and final_newline else "")
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_bytes(text.encode("utf-8"))
        if renamed and source_file.exists() and not source_file.samefile(dest_file):
            source_file.unlink()
        applied_files.append(str(dest_file))

    return True, "Applied patch without git to:\n" + "\n".join(applied_files) + "\n"


def _split_patch_sections(patch_text: str) -> list[str]:
    """Split a patch into per-file sections for git-style and plain unified diffs."""

    if "diff --git " in patch_text:
        return patch_text.split("diff --git ")
    # Plain unified diff: each "--- " / "+++ " / "@@" header starts another file.
    lines = patch_text.splitlines()
    sections: list[list[str]] = [[]]
    for index, line in enumerate(lines):
        is_header = (
            line.startswith("--- ")
            and index + 2 < len(lines)
            and lines[index + 1].startswith("+++ ")
            and lines[index + 2].startswith("@@")
        )
        if is_header and sections[-1]:
            sections.append([])
        sections[-1].append(line)
    return ["\n".join(section) for section in sections]


def _extract_patch_target(
    lines: list[str],
    patch_file: Path,
) -> tuple[str, str, bool, list[str]]:
    """Extract (old path, new path, renamed, hunk lines) from one patch section.

    ``a/`` and ``b/`` prefixes are dropped and a trailing tab-delimited timestamp
    is ignored; ``/dev/null`` (or a ``new file`` / ``deleted file`` mode line)
    marks a created or deleted file, and ``rename from`` / ``rename to`` a rename.
    """

    first = lines[0]
    if first.startswith("--- "):
        old_path = new_path = ""
        body = lines
    else:
        header_parts = first.split()
        if len(header_parts) < 2:
            return "", "", False, lines
        old_path = _strip_diff_prefix(header_parts[0], "a/")
        new_path = _strip_diff_prefix(header_parts[1], "b/")
        body = lines[1:]

    renamed = False
    for line in body:
        if line.startswith("@@"):
            break
        if line.startswith("--- "):
            old_path = _strip_diff_prefix(line[4:].split("\t", 1)[0].strip(), "a/")
        elif line.startswith("+++ "):
            new_path = _strip_diff_prefix(line[4:].split("\t", 1)[0].strip(), "b/")
        elif line.startswith("rename from "):
            old_path = line[len("rename from ") :].strip()
            renamed = True
        elif line.startswith("rename to "):
            new_path = line[len("rename to ") :].strip()
            renamed = True
        elif line.startswith("new file mode"):
            old_path = _DEV_NULL
        elif line.startswith("deleted file mode"):
            new_path = _DEV_NULL
    return old_path, new_path, renamed, body


def _strip_diff_prefix(path: str, prefix: str) -> str:
    # Strip only this side's prefix: with --no-prefix, a real top-level b/
    # directory on the old side must survive.
    return path[len(prefix) :] if path.startswith(prefix) else path


def _workspace_file(repo_path: Path, rel_path: str) -> Path | None:
    """Resolve a patch path inside the workspace, or None if it would leave it."""

    text = rel_path.replace("\\", "/")
    normalized = posixpath.normpath(text)
    if (
        not text
        or text.startswith("/")
        or _WINDOWS_DRIVE.match(text)
        or normalized == ".."
        or normalized.startswith("../")
    ):
        return None
    root = Path(repo_path).resolve()
    candidate = (root / normalized).resolve()
    return candidate if candidate.is_relative_to(root) else None


def _patched_final_newline(lines: list[str]) -> bool | None:
    """Return whether the patched file should end with a newline, if the patch says.

    A ``\\ No newline at end of file`` marker after an added or context line means
    the new file lacks it; a marker only after removed lines means the patch adds
    it. With no marker the patch leaves the file's final newline unchanged (None).
    """

    old_side_marker = False
    previous = ""
    for line in lines:
        if line.startswith("\\"):
            if previous.startswith("-"):
                old_side_marker = True
            else:
                return False
        previous = line
    return True if old_side_marker else None


def parse_unified_hunks(
    lines: list[str],
    target_file: Path,
) -> list[tuple[list[str], list[str], int]] | str:
    """Parse unified diff hunks into source chunks, target chunks and declared old-start lines."""

    hunks: list[tuple[list[str], list[str], int]] = []
    current_source: list[str] = []
    current_target: list[str] = []
    in_hunk = False
    old_start = 0
    _hdr = re.compile(r"^@@ -(\d+)")

    for line in lines:
        if line.startswith(("index ", "--- ", "+++ ")):
            continue
        if line.startswith("@@"):
            if in_hunk:
                hunks.append((current_source, current_target, old_start))
            current_source = []
            current_target = []
            in_hunk = True
            m = _hdr.match(line)
            old_start = int(m.group(1)) if m else 0
            continue
        if not in_hunk:
            continue
        if line.startswith(" "):
            current_source.append(line[1:])
            current_target.append(line[1:])
        elif line == "":
            # A blank context line: many diff tools emit it as a zero-length line
            # instead of a single space. Treat it as unchanged context (git apply
            # tolerates this; the strict reader must too or real diffs fail).
            current_source.append("")
            current_target.append("")
        elif line.startswith("\\"):
            # "\ No newline at end of file" marker — metadata, not content.
            continue
        elif line.startswith("-"):
            current_source.append(line[1:])
        elif line.startswith("+"):
            current_target.append(line[1:])
        else:
            return f"Unsupported patch line while patching {target_file}: {line}\n"

    if in_hunk:
        hunks.append((current_source, current_target, old_start))
    return hunks


def find_subsequence(
    lines: list[str],
    chunk: list[str],
    start: int,
    anchor: int | None = None,
) -> int:
    """Find a sequence of lines inside a larger line list.

    Without ``anchor`` the first match at or after ``start`` wins. With an
    ``anchor`` (the hunk's declared position) the match nearest to it wins, so
    repeated context patches the intended occurrence; ties go to the earlier one.
    """

    if not chunk:
        return start
    last = len(lines) - len(chunk) + 1
    matches = [
        idx
        for idx in range(start, max(last, start))
        if lines[idx : idx + len(chunk)] == chunk
    ]
    if not matches:
        return -1
    if anchor is None:
        return matches[0]
    return min(matches, key=lambda idx: (abs(idx - anchor), idx))
