"""OpenAI-backed code agent integrations for ACBench."""

from __future__ import annotations

import os
import json
from pathlib import Path
import re
from time import perf_counter
from typing import Any
import zlib

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised in environments without openai installed
    OpenAI = None

from acbench.agents.coupling import format_ops_diagnosis
from acbench.agents.telemetry import summarize_call_records, timed_call
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec
from acbench.paths import resolve_repo_path

_LANGUAGE_SUFFIXES = {"python": ".py", "go": ".go"}
_SKIPPED_DIRS = {"tests", "test", "testdata", "vendor", "node_modules", "__pycache__"}
TRUNCATED_RESPONSE_ERROR = (
    "The response was cut off at the output token limit, so the patch may be incomplete. "
    "Return the complete patch, keeping it short."
)


class OpenAICodePatchAgent:
    """Generate a unified diff patch for standalone repository-backed code tasks."""

    def generate_patch(
        self,
        scenario: ScenarioSpec,
        run_config: RunConfig,
        *,
        output_dir: Path,
    ) -> dict[str, str]:
        section = dict(run_config.code_agent_config or {})
        model = str(section.get("model", run_config.openai_model)).strip()
        api_key_env = str(
            section.get(
                "api_key_env",
                run_config.openai_api_key_env or "OPENAI_API_KEY",
            )
        ).strip()
        base_url = str(section.get("base_url", run_config.openai_base_url or "")).strip()
        api_mode = self._normalize_api_mode(section.get("api", "responses"))
        temperature = section.get("temperature")
        seed = section.get("seed")

        api_key = os.environ.get(api_key_env or "OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError(
                f"Environment variable `{api_key_env}` is not set."
            )
        if not model:
            raise ValueError("RunConfig.openai_model is required for OpenAICodePatchAgent.")
        if OpenAI is None:
            raise ImportError(
                "OpenAICodePatchAgent requires the `openai` package. Install dependencies or patch the client in tests."
            )

        prompt = self._build_prompt(scenario, run_config)
        client = OpenAI(
            api_key=api_key,
            base_url=base_url or None,
        )
        started = perf_counter()
        call_records: list[dict[str, Any]] = []
        raw_text, call_record = self._generate_text(
            client,
            api_mode,
            label="initial_answer",
            model=model,
            prompt=prompt,
            temperature=temperature,
            seed=seed,
        )
        call_records.append(call_record)
        prompt_path = output_dir / "openai_prompt.txt"
        response_path = output_dir / "openai_response.txt"
        telemetry_path = output_dir / "openai_code_telemetry.json"
        prompt_path.write_text(prompt, encoding="utf-8")
        response_path.write_text(raw_text, encoding="utf-8")
        patch_text = self._extract_patch(raw_text)
        patch_text = self._normalize_unified_diff(patch_text)
        validation_error = self._patch_error(patch_text, call_record)
        for _ in range(3):
            if not validation_error:
                break
            repair_prompt = self._build_patch_repair_prompt(
                original_prompt=prompt,
                invalid_patch=patch_text,
                validation_error=validation_error,
            )
            repair_text, call_record = self._generate_text(
                client,
                api_mode,
                label=f"repair_answer_{len(call_records)}",
                model=model,
                prompt=repair_prompt,
                temperature=temperature,
                seed=seed,
            )
            call_records.append(call_record)
            raw_text = f"{raw_text}\n\n--- PATCH REPAIR ---\n{repair_text}"
            response_path.write_text(raw_text, encoding="utf-8")
            patch_text = self._extract_patch(repair_text)
            patch_text = self._normalize_unified_diff(patch_text)
            validation_error = self._patch_error(patch_text, call_record)
        telemetry = summarize_call_records(
            call_records,
            wall_time_seconds=perf_counter() - started,
        )
        telemetry_path.write_text(json.dumps(telemetry, indent=2), encoding="utf-8")
        if validation_error:
            raise ValueError(f"Model returned an invalid unified diff after retries: {validation_error}")

        patch_path = output_dir / "openai_generated_patch.diff"
        patch_path.write_text(patch_text, encoding="utf-8")
        return {
            "patch_text": patch_text,
            "prompt_path": str(prompt_path),
            "response_path": str(response_path),
            "generated_patch_path": str(patch_path),
            "telemetry": telemetry,
            "telemetry_path": str(telemetry_path),
        }

    def complete_patch(
        self,
        prompt: str,
        *,
        model: str,
        base_url: str = "",
        api_key_env: str = "OPENAI_API_KEY",
        api: str = "chat_completions",
        temperature: float | None = None,
        seed: int | None = None,
        retries: int = 2,
        timeout: float = 240.0,
    ) -> str:
        """Return a validated unified-diff patch for an ARBITRARY prompt, reusing the
        SAME robust extract -> normalize -> validate -> repair-retry path as
        generate_patch. Iterative callers (e.g. the perf optimization loop, which
        injects per-iteration feedback into the prompt) get the identical generation
        quality as the single-shot agent, so models are compared on a FAIR mechanism
        rather than a weaker hand-rolled extractor.

        Returns '' on ANY failure -- still invalid after retries OR a transient
        API/network error -- so iterative callers degrade to one failed attempt
        (applied=False) instead of aborting the whole multi-hour run. A per-request
        timeout (default 240s) caps a stalled-but-connected backend."""
        if OpenAI is None:
            raise ImportError("complete_patch requires the `openai` package.")
        client = OpenAI(
            api_key=os.environ.get(api_key_env or "OPENAI_API_KEY", "") or "EMPTY",
            base_url=base_url or None,
            timeout=timeout,
        )
        api_mode = self._normalize_api_mode(api)
        try:
            raw, record = self._generate_text(
                client, api_mode, label="loop_answer", model=model,
                prompt=prompt, temperature=temperature, seed=seed,
            )
            patch = self._normalize_unified_diff(self._extract_patch(raw))
            err = self._patch_error(patch, record)
            for i in range(max(0, retries)):
                if not err:
                    break
                repair = self._build_patch_repair_prompt(
                    original_prompt=prompt, invalid_patch=patch, validation_error=err,
                )
                raw, record = self._generate_text(
                    client, api_mode, label=f"loop_repair_{i}", model=model,
                    prompt=repair, temperature=temperature, seed=seed,
                )
                patch = self._normalize_unified_diff(self._extract_patch(raw))
                err = self._patch_error(patch, record)
        except Exception:
            return ""
        return "" if err else patch

    @staticmethod
    def _normalize_api_mode(api_mode: Any) -> str:
        normalized = str(api_mode or "responses").strip().lower().replace(".", "_")
        aliases = {
            "response": "responses",
            "responses": "responses",
            "chat_completion": "chat_completions",
            "chat_completions": "chat_completions",
        }
        if normalized not in aliases:
            raise ValueError(
                "Unsupported OpenAI-compatible API mode "
                f"`{api_mode}`. Use `responses` or `chat_completions`."
            )
        return aliases[normalized]

    @classmethod
    def _generate_text(
        cls,
        client: OpenAI,
        api_mode: str,
        *,
        label: str,
        model: str,
        prompt: str,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if api_mode == "responses":
            kwargs: dict[str, Any] = {"model": model, "input": prompt}
            if temperature is not None:
                kwargs["temperature"] = temperature
            response, call_record = timed_call(label, client.responses.create, **kwargs)
            call_record["truncated"] = cls._response_truncated(response)
            return cls._extract_model_text(response), call_record

        chat_kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            chat_kwargs["temperature"] = temperature
        if seed is not None:
            chat_kwargs["seed"] = seed
        response, call_record = timed_call(
            label,
            client.chat.completions.create,
            **chat_kwargs,
        )
        call_record["truncated"] = cls._response_truncated(response)
        return cls._extract_model_text(response), call_record

    @staticmethod
    def _response_truncated(response: Any) -> bool:
        """Whether a Responses or Chat Completions reply stopped at the token limit."""

        if getattr(response, "status", None) == "incomplete":
            return True
        return any(
            getattr(choice, "finish_reason", None) == "length"
            for choice in getattr(response, "choices", None) or []
        )

    @classmethod
    def _patch_error(cls, patch_text: str, call_record: dict[str, Any]) -> str:
        """Validation error for a generated patch, counting a truncated reply as one."""

        error = cls._validate_unified_diff(patch_text)
        if not error and call_record.get("truncated"):
            return TRUNCATED_RESPONSE_ERROR
        return error

    @staticmethod
    def _extract_model_text(response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text:
            return output_text

        choices = getattr(response, "choices", None) or []
        for choice in choices:
            message = getattr(choice, "message", None)
            if message is None:
                continue
            content = getattr(message, "content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    text = ""
                    if isinstance(item, dict):
                        text = str(item.get("text", "")).strip()
                    else:
                        text = str(getattr(item, "text", "")).strip()
                    if text:
                        parts.append(text)
                if parts:
                    return "\n".join(parts)
        return ""

    def _build_prompt(self, scenario: ScenarioSpec, run_config: RunConfig | None = None) -> str:
        repository_path = scenario.service.repository_path or ""
        if repository_path:
            repo_root = resolve_repo_path(repository_path)
            return self._build_repository_prompt(scenario, repo_root, run_config)
        raise ValueError("OpenAICodePatchAgent requires service.repository_path.")

    def _build_repository_prompt(
        self,
        scenario: ScenarioSpec,
        repo_root: Path,
        run_config: RunConfig | None = None,
    ) -> str:
        hide_location = bool(getattr(run_config, "hide_fault_location", False)) if run_config else False
        fault_files = list(scenario.code_fault.target_files if scenario.code_fault else [])
        if hide_location:
            # Do not single out the buggy file: show all source so the diagnosis
            # has to provide the localization. The fault files are always among
            # the files shown, in path order, or the task could not be solved.
            target_files = self._discover_default_targets(
                repo_root, required=fault_files, language=scenario.build.language
            )
            files_label = "Repository source files (the faulty file is NOT identified — localize it):"
        else:
            target_files = fault_files
            if not target_files:
                target_files = self._discover_default_targets(
                    repo_root, language=scenario.build.language
                )
            files_label = "Target files and nearby test context:"

        diagnosis = getattr(run_config, "upstream_ops_diagnosis", None) if run_config else None
        diagnosis_section = format_ops_diagnosis(diagnosis)

        sections = [
            "You are fixing a repository-backed benchmark task.",
            "Return only a valid unified diff patch.",
            f"Scenario ID: {scenario.scenario_id}",
            f"Title: {scenario.title}",
            f"Notes: {scenario.notes}",
            *([diagnosis_section] if diagnosis_section else []),
            f"Repository root: {repo_root}",
            "Rebuild commands:",
            *[f"- {command}" for command in scenario.build.rebuild_cmds],
            "Test commands:",
            *[f"- {command}" for command in scenario.build.test_cmds],
            files_label,
        ]
        # Optional context budget (chars). Default 0 = unbounded (synthetic fixtures
        # are tiny). Real-world repos have very large files; without a budget the
        # prompt can exceed the model context window and the request is rejected,
        # silently dropping the scenario. When set, large files are truncated
        # head+tail with an explicit marker so the request always fits.
        max_chars = int(os.environ.get("ACBENCH_MAX_PROMPT_CHARS", "0") or "0")
        file_sections: list[tuple[str, str]] = []
        for relative_path in target_files:
            file_path = repo_root / relative_path
            if not file_path.exists():
                continue
            file_sections.append((relative_path, file_path.read_text(encoding="utf-8")))
        if max_chars > 0 and file_sections:
            total = sum(len(c) for _, c in file_sections)
            if total > max_chars:
                per = max(2000, max_chars // len(file_sections))
                file_sections = [(p, self._truncate_to(c, per)) for p, c in file_sections]
        for relative_path, content in file_sections:
            sections.append(f"\n--- FILE: {relative_path} ---")
            sections.append(content)

        for test_path in self._discover_test_files(repo_root):
            sections.append(f"\n--- TEST: {test_path} ---")
            sections.append((repo_root / test_path).read_text(encoding="utf-8"))

        sections.append(
            "\nReturn only the patch. Do not include explanations, markdown fences, or prose."
        )
        return "\n".join(sections)

    @staticmethod
    def _build_patch_repair_prompt(
        *,
        original_prompt: str,
        invalid_patch: str,
        validation_error: str,
    ) -> str:
        return "\n".join(
            [
                "Your previous answer was not a valid unified diff patch.",
                f"Validation error: {validation_error}",
                "Return a corrected unified diff patch only.",
                "Do not include commentary, placeholders, ellipses, or omitted sections.",
                "Every hunk header must match the actual number of removed and added lines.",
                "Original task prompt:",
                original_prompt,
                "Previous invalid patch:",
                invalid_patch,
            ]
        )

    @staticmethod
    def _validate_unified_diff(patch_text: str) -> str:
        text = patch_text.strip()
        if not text:
            return "Patch is empty."
        if "omitted for brevity" in text.lower():
            return "Patch contains placeholder prose."
        lines = text.splitlines()
        has_git_header = any(line.startswith("diff --git ") for line in lines)
        has_plain_headers = any(line.startswith("--- ") for line in lines) and any(
            line.startswith("+++ ") for line in lines
        )
        if not has_git_header and not has_plain_headers:
            return "Patch does not contain recognizable diff file headers."
        if not any(line.startswith("@@") for line in lines):
            return "Patch does not contain any hunk headers."

        saw_effective_change = False
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.startswith("@@"):
                i += 1
                continue
            match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            old_count = int(match.group(2) or "1") if match else None
            new_count = int(match.group(4) or "1") if match else None
            removed = 0
            added = 0
            removed_block: list[str] = []
            added_block: list[str] = []

            def flush_change_block() -> None:
                nonlocal saw_effective_change
                if not removed_block and not added_block:
                    return
                if removed_block != added_block:
                    saw_effective_change = True
                removed_block.clear()
                added_block.clear()

            i += 1
            while i < len(lines):
                current = lines[i]
                if current.startswith("@@") or OpenAICodePatchAgent._is_patch_start(lines, i):
                    flush_change_block()
                    i -= 1
                    break
                if current.startswith("index "):
                    i += 1
                    continue
                if current.startswith("\\ No newline at end of file"):
                    i += 1
                    continue
                if current.startswith("+"):
                    added += 1
                    added_block.append(current[1:])
                elif current.startswith("-"):
                    removed += 1
                    removed_block.append(current[1:])
                elif current.startswith(" "):
                    flush_change_block()
                    removed += 1
                    added += 1
                else:
                    return f"Unsupported diff line: {current}"
                i += 1
            flush_change_block()
            if old_count is not None and new_count is not None and (
                removed != old_count or added != new_count
            ):
                return (
                    f"Hunk header count mismatch: expected -{old_count} +{new_count}, "
                    f"saw -{removed} +{added}."
                )
            i += 1
        if not saw_effective_change:
            return "Patch does not change any file contents."
        return ""

    @staticmethod
    def _normalize_unified_diff(patch_text: str) -> str:
        text = patch_text.strip()
        if not text:
            return ""
        lines = text.splitlines()
        normalized: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.startswith("@@"):
                normalized.append(line)
                i += 1
                continue

            match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$", line)
            if not match:
                normalized.append(line)
                i += 1
                continue

            old_start = int(match.group(1))
            new_start = int(match.group(3))
            declared = (int(match.group(2) or "1"), int(match.group(4) or "1"))
            suffix = match.group(5) or ""
            hunk_lines: list[str] = []
            i += 1
            while i < len(lines):
                if lines[i].startswith("@@") or OpenAICodePatchAgent._is_patch_start(lines, i):
                    break
                hunk_lines.append(lines[i])
                i += 1

            # Models often write a blank context line as an empty line instead of
            # a single space; git apply accepts that, so treat it as context.
            # Trailing empty lines usually just separate this hunk from the next
            # file section: keep them only if the declared counts include them.
            body = [" " if current == "" else current for current in hunk_lines]
            counts = OpenAICodePatchAgent._count_hunk_lines(body)
            while body and hunk_lines[len(body) - 1] == "" and counts != declared:
                body.pop()
                counts = OpenAICodePatchAgent._count_hunk_lines(body)

            if counts is None:
                normalized.append(line)
                normalized.extend(hunk_lines)
                continue
            normalized.append(f"@@ -{old_start},{counts[0]} +{new_start},{counts[1]} @@{suffix}")
            normalized.extend(body)

        return "\n".join(normalized).strip()

    @staticmethod
    def _count_hunk_lines(hunk_lines: list[str]) -> tuple[int, int] | None:
        """Return the (old, new) line counts of a hunk body, or None if a line is not a diff line."""

        old_count = 0
        new_count = 0
        for current in hunk_lines:
            if current.startswith("-"):
                old_count += 1
            elif current.startswith("+"):
                new_count += 1
            elif current.startswith(" "):
                old_count += 1
                new_count += 1
            elif not current.startswith("\\ No newline at end of file"):
                return None
        return old_count, new_count

    @staticmethod
    def _discover_default_targets(
        repo_root: Path,
        *,
        required: list[str] | tuple[str, ...] = (),
        language: str = "python",
        limit: int = 10,
    ) -> list[str]:
        """Return up to `limit` source files in path order, always including `required`.

        Files are matched by the required files' extensions, else by `language`;
        `src/` is searched when it holds any, else the whole repository. Tests,
        vendored code and hidden directories are skipped.
        """

        suffixes = {Path(path).suffix for path in required if Path(path).suffix}
        if not suffixes:
            suffixes = {_LANGUAGE_SUFFIXES.get(language, ".py")}

        def source_files(root_dir: Path) -> list[str]:
            found = []
            for path in root_dir.rglob("*"):
                relative = path.relative_to(repo_root).as_posix()
                parts = relative.split("/")
                if (
                    path.suffix not in suffixes
                    or not path.is_file()
                    or any(part.startswith(".") or part in _SKIPPED_DIRS for part in parts[:-1])
                    or parts[-1].endswith("_test.go")
                    or parts[-1].startswith("test_")
                ):
                    continue
                found.append(relative)
            return sorted(found)

        candidates = source_files(repo_root / "src") if (repo_root / "src").is_dir() else []
        if not candidates:
            candidates = source_files(repo_root)
        required_paths = [path.replace("\\", "/") for path in required]
        ordered = sorted(set(candidates) | set(required_paths))
        if len(ordered) <= limit:
            return ordered
        # Show a contiguous run in path order that contains the fault file at an
        # offset derived from its path, so it does not stand out from the rest.
        anchor = ordered.index(required_paths[0]) if required_paths else 0
        offset = zlib.crc32(required_paths[0].encode("utf-8")) % limit if required_paths else 0
        start = min(max(anchor - offset, 0), len(ordered) - limit)
        window = ordered[start : start + limit]
        missing = [path for path in required_paths if path not in window]
        if missing:
            window = [path for path in window if path not in required_paths][: limit - len(required_paths)]
            window += required_paths
        return sorted(window)

    @staticmethod
    def _truncate_to(text: str, cap: int) -> str:
        """Truncate a file body to ~cap chars, keeping head (2/3) and tail (1/3)
        with an explicit marker, so very large files still fit the context window
        without silently dropping the scenario."""
        if cap <= 0 or len(text) <= cap:
            return text
        head = (cap * 2) // 3
        tail = cap - head
        dropped = text[head: len(text) - tail]
        n_lines = dropped.count("\n")
        return (
            text[:head]
            + f"\n\n... [{n_lines} lines truncated to fit the context budget] ...\n\n"
            + text[len(text) - tail:]
        )

    @staticmethod
    def _discover_test_files(repo_root: Path) -> list[str]:
        tests_dir = repo_root / "tests"
        if not tests_dir.exists():
            return []
        files = [
            str(path.relative_to(repo_root)).replace("\\", "/")
            for path in tests_dir.rglob("test_*.py")
        ]
        return files[:10]

    @staticmethod
    def _extract_patch(response_text: str) -> str:
        text = response_text.strip()
        if not text:
            return ""

        fenced_patch = OpenAICodePatchAgent._extract_fenced_patch(text)
        if fenced_patch:
            return fenced_patch

        file_block_patch = OpenAICodePatchAgent._extract_file_block_patch(text)
        if file_block_patch:
            return file_block_patch

        lines = text.splitlines()
        patch_lines: list[str] = []
        started = False
        saw_hunk = False
        # Old/new lines the current hunk header still expects; used to tell a
        # blank context line written as "" from the blank line after a patch.
        old_left = new_left = 0
        in_file_header = False

        for index, line in enumerate(lines):
            if not started and not OpenAICodePatchAgent._is_patch_start(lines, index):
                continue
            if not started:
                started = True

            if line == "" and saw_hunk:
                if OpenAICodePatchAgent._blank_is_context(lines, index, old_left, new_left):
                    patch_lines.append(" ")
                    old_left -= 1
                    new_left -= 1
                    continue
                if OpenAICodePatchAgent._next_section_starts(lines, index + 1):
                    continue
                break

            if OpenAICodePatchAgent._looks_like_patch_line(line):
                patch_lines.append(line)
                if OpenAICodePatchAgent._is_patch_start(lines, index):
                    in_file_header = line.startswith("--- ")
                    old_left = new_left = 0
                elif in_file_header and line.startswith("+++ "):
                    in_file_header = False
                elif line.startswith("@@"):
                    saw_hunk = True
                    header = re.match(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)
                    old_left = int(header.group(1) or "1") if header else 0
                    new_left = int(header.group(2) or "1") if header else 0
                elif line.startswith(" "):
                    old_left -= 1
                    new_left -= 1
                elif line.startswith("-"):
                    old_left -= 1
                elif line.startswith("+"):
                    new_left -= 1
                continue

            if saw_hunk and patch_lines:
                break

        if patch_lines:
            return "\n".join(patch_lines).strip()
        return text

    @staticmethod
    def _next_section_starts(lines: list[str], index: int) -> bool:
        """Whether the next non-empty line from `index` starts another file section or hunk."""

        while index < len(lines) and lines[index] == "":
            index += 1
        if index >= len(lines):
            return False
        return lines[index].startswith("@@") or OpenAICodePatchAgent._is_patch_start(lines, index)

    @staticmethod
    def _extract_fenced_patch(text: str) -> str:
        # Models often put each file's diff in its own fence; keep every block
        # that patches a file not already covered, so later files are not lost.
        # A later block that only edits tests is usually an optional suggestion;
        # scenarios forbid test edits, so adding it would reject the whole patch.
        block_pattern = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.DOTALL)
        blocks: list[str] = []
        seen_targets: set[str] = set()
        for match in block_pattern.finditer(text):
            candidate = match.group(1).strip()
            if not candidate or not OpenAICodePatchAgent._contains_patch_markers(candidate):
                continue
            targets = OpenAICodePatchAgent._patch_targets(candidate)
            if blocks and (
                targets & seen_targets
                or not targets
                or all(OpenAICodePatchAgent._is_test_path(path) for path in targets)
            ):
                continue
            seen_targets |= targets
            blocks.append(candidate)
        return "\n".join(blocks)

    @staticmethod
    def _patch_targets(patch_text: str) -> set[str]:
        """Files a diff writes, without `b/` prefixes or header timestamps."""

        targets = set()
        for line in patch_text.splitlines():
            if line.startswith("+++ "):
                path = line[4:].split("\t", 1)[0].strip()
            elif line.startswith("diff --git "):
                parts = line.split()
                path = parts[3] if len(parts) >= 4 else ""
            else:
                continue
            path = path[2:] if path.startswith("b/") else path
            if path and path != "/dev/null":
                targets.add(path)
        return targets

    @staticmethod
    def _is_test_path(path: str) -> bool:
        parts = path.replace("\\", "/").split("/")
        return (
            any(part in ("tests", "test") for part in parts[:-1])
            or parts[-1].startswith("test_")
            or parts[-1].endswith(("_test.go", "_test.py"))
        )

    @staticmethod
    def _blank_is_context(lines: list[str], index: int, old_left: int, new_left: int) -> bool:
        """Whether the empty line at `index` is a blank context line of the current hunk.

        It is only if counting it and the lines after it uses up the header's
        old/new counts exactly at a boundary; otherwise it ends the patch (for
        example a header that over-counts, followed by a bullet list).
        """

        old_left -= 1
        new_left -= 1
        index += 1
        while old_left > 0 or new_left > 0:
            if old_left < 0 or new_left < 0 or index >= len(lines):
                return False
            current = lines[index]
            if current == "" or current.startswith(" "):
                old_left -= 1
                new_left -= 1
            elif current.startswith("-") and not OpenAICodePatchAgent._is_patch_start(lines, index):
                old_left -= 1
            elif current.startswith("+"):
                new_left -= 1
            elif not current.startswith("\\ No newline at end of file"):
                return False
            index += 1
        if old_left < 0 or new_left < 0:
            return False
        return (
            index >= len(lines)
            or lines[index] == ""
            or lines[index].startswith("@@")
            or OpenAICodePatchAgent._is_patch_start(lines, index)
        )

    @staticmethod
    def _extract_file_block_patch(text: str) -> str:
        lines = text.splitlines()
        patch_lines: list[str] = []
        found_block = False
        index = 0

        while index < len(lines):
            match = re.match(r"^--- FILE:\s+(.+?)\s+---$", lines[index].strip())
            if not match:
                index += 1
                continue

            found_block = True
            relative_path = match.group(1).strip().replace("\\", "/")
            patch_lines.append(f"--- a/{relative_path}")
            patch_lines.append(f"+++ b/{relative_path}")
            index += 1
            in_hunk = False

            while index < len(lines):
                current = lines[index]
                if re.match(r"^--- FILE:\s+(.+?)\s+---$", current.strip()):
                    break
                if current.startswith("--- PATCH REPAIR ---"):
                    break
                if current.startswith("@@"):
                    in_hunk = True
                # Keep empty lines inside hunks: they may be blank context lines,
                # and _normalize_unified_diff drops the ones that are separators.
                if current.startswith(("@@", "+", "-", " ", "\\ No newline")) or (
                    in_hunk and current == ""
                ):
                    patch_lines.append(current)
                index += 1

        if not found_block:
            return ""
        return "\n".join(patch_lines).strip()

    @staticmethod
    def _contains_patch_markers(text: str) -> bool:
        lines = text.splitlines()
        return any(line.startswith("@@") for line in lines) and (
            any(line.startswith("diff --git ") for line in lines)
            or (
                any(line.startswith("--- ") for line in lines)
                and any(line.startswith("+++ ") for line in lines)
            )
        )

    @staticmethod
    def _is_patch_start(lines: list[str], index: int) -> bool:
        line = lines[index]
        if line.startswith("diff --git "):
            return True
        if line.startswith("--- "):
            return index + 1 < len(lines) and lines[index + 1].startswith("+++ ")
        return False

    @staticmethod
    def _looks_like_patch_line(line: str) -> bool:
        return line.startswith(
            (
                "diff --git ",
                "index ",
                "--- ",
                "+++ ",
                "@@",
                "+",
                "-",
                " ",
                "\\ No newline at end of file",
            )
        )
