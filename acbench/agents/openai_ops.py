"""OpenAI-backed ops agent integrations for ACBench."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from time import perf_counter
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised in environments without openai installed
    OpenAI = None

from acbench.agents.telemetry import summarize_call_records, timed_call
from acbench.executors.backends.ops.runtime import NativeOpsProblem


class OpenAIOpsAgent:
    """Use an OpenAI-compatible model to produce structured ops assessments."""

    def __init__(self) -> None:
        self.model = ""
        self.api_key_env = "OPENAI_API_KEY"
        self.base_url = ""
        self.api_mode = "responses"
        self.last_prompt = ""
        self.last_response = ""
        self.last_assessment: dict[str, Any] = {}

    def configure(
        self,
        run_config=None,
        *,
        model: str = "",
        api_key_env: str = "OPENAI_API_KEY",
        base_url: str = "",
        api: str = "responses",
        **_: Any,
    ) -> None:
        """Load runtime configuration before the problem starts."""

        if run_config is not None:
            section = dict(getattr(run_config, "ops_agent_config", {}) or {})
            model = str(section.get("model", getattr(run_config, "openai_model", model)))
            api_key_env = str(
                section.get(
                    "api_key_env",
                    getattr(run_config, "openai_api_key_env", api_key_env),
                )
            )
            base_url = str(
                section.get(
                    "base_url",
                    getattr(run_config, "openai_base_url", base_url),
                )
            )
            api_mode = str(section.get("api", "responses"))
        else:
            api_mode = api

        self.model = model
        self.api_key_env = api_key_env or "OPENAI_API_KEY"
        self.base_url = base_url or ""
        self.api_mode = OpenAIOpsAgent._normalize_api_mode(api_mode)

    def analyze(
        self,
        problem: NativeOpsProblem,
        *,
        output_dir: Path,
    ) -> dict[str, Any]:
        """Generate one structured assessment for an ops task."""

        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            raise ValueError(f"Environment variable `{self.api_key_env}` is not set.")
        if not self.model:
            raise ValueError("OpenAIOpsAgent requires a configured OpenAI model.")
        if OpenAI is None:
            raise ImportError(
                "OpenAIOpsAgent requires the `openai` package. Install dependencies or patch the client in tests."
            )

        client = OpenAI(api_key=api_key, base_url=self.base_url or None)
        prompt = self._build_prompt(problem)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        prompt_path = Path(output_dir) / "openai_ops_prompt.txt"
        response_path = Path(output_dir) / "openai_ops_response.txt"
        assessment_path = Path(output_dir) / "openai_ops_assessment.json"
        telemetry_path = Path(output_dir) / "openai_ops_telemetry.json"

        started = perf_counter()
        call_records: list[dict[str, Any]] = []
        raw_text, call_record = self._generate_text(
            client,
            self.api_mode,
            label="initial_answer",
            model=self.model,
            prompt=prompt,
        )
        call_records.append(call_record)
        prompt_path.write_text(prompt, encoding="utf-8")
        response_path.write_text(raw_text, encoding="utf-8")

        assessment = self._extract_assessment(raw_text)
        validation_error = self._validate_assessment(assessment)

        for _ in range(3):
            if not validation_error:
                break
            repair_prompt = self._build_repair_prompt(
                original_prompt=prompt,
                invalid_response=raw_text,
                validation_error=validation_error,
            )
            repair_text, call_record = self._generate_text(
                client,
                self.api_mode,
                label=f"repair_answer_{len(call_records)}",
                model=self.model,
                prompt=repair_prompt,
            )
            call_records.append(call_record)
            raw_text = f"{raw_text}\n\n--- ASSESSMENT REPAIR ---\n{repair_text}"
            response_path.write_text(raw_text, encoding="utf-8")
            assessment = self._extract_assessment(repair_text)
            validation_error = self._validate_assessment(assessment)

        telemetry = summarize_call_records(
            call_records,
            wall_time_seconds=perf_counter() - started,
        )
        telemetry_path.write_text(json.dumps(telemetry, indent=2), encoding="utf-8")

        if validation_error:
            raise ValueError(
                f"Model returned an invalid ops assessment after retries: {validation_error}"
            )

        assessment_path.write_text(json.dumps(assessment, indent=2), encoding="utf-8")
        self.last_prompt = prompt
        self.last_response = raw_text
        self.last_assessment = assessment
        return {
            "assessment": assessment,
            "prompt_path": str(prompt_path),
            "response_path": str(response_path),
            "assessment_path": str(assessment_path),
            "telemetry": telemetry,
            "telemetry_path": str(telemetry_path),
        }

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
    ) -> tuple[str, dict[str, Any]]:
        if api_mode == "responses":
            response, call_record = timed_call(
                label,
                client.responses.create,
                model=model,
                input=prompt,
            )
            return cls._extract_model_text(response), call_record

        response, call_record = timed_call(
            label,
            client.chat.completions.create,
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return cls._extract_model_text(response), call_record

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

    def _build_prompt(self, problem: NativeOpsProblem) -> str:
        prompt = {
            "task": {
                "problem_id": problem.problem_id,
                "application": problem.application,
                "service": problem.service,
                "deployment": problem.deployment,
                "summary": problem.task_summary,
                "instructions": problem.task_instructions,
                "acceptance_notes": problem.acceptance_notes,
            },
            "incident": {
                "issue_text": problem.issue_text,
                "error_logs": problem.error_logs,
                "reproduction_steps": problem.reproduction_steps,
                "relevant_files": problem.relevant_files,
                "notes": problem.visible_notes,
            },
            "requirements": {
                "must_detect": problem.require_detection,
                "must_localize": problem.require_localization,
                "must_repair": problem.require_repair,
            },
            "response_schema": {
                "detected": "boolean",
                "localized": "boolean",
                "repaired": "boolean",
                "summary": "short string",
                "root_cause": "short string",
                "remediation": "short string",
                "evidence": ["list of short evidence strings"],
            },
        }
        return "\n".join(
            [
                "You are evaluating an operational incident for an ACBench task.",
                "Return only one JSON object matching the requested schema.",
                "Do not use markdown fences.",
                "Base your answer only on the provided incident evidence.",
                json.dumps(prompt, indent=2),
            ]
        )

    @staticmethod
    def _build_repair_prompt(
        *,
        original_prompt: str,
        invalid_response: str,
        validation_error: str,
    ) -> str:
        return "\n".join(
            [
                "Your previous answer was not a valid JSON ops assessment.",
                f"Validation error: {validation_error}",
                "Return only one JSON object with the required fields.",
                "Booleans must be true or false, and evidence must be a JSON array of strings.",
                "Original task prompt:",
                original_prompt,
                "Previous invalid response:",
                invalid_response,
            ]
        )

    @staticmethod
    def _extract_assessment(response_text: str) -> dict[str, Any]:
        text = response_text.strip()
        if not text:
            return {}

        if text.startswith("```"):
            fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if fence_match:
                text = fence_match.group(1).strip()

        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(text[index:])
                if isinstance(parsed, dict):
                    return OpenAIOpsAgent._normalize_assessment(parsed)
            except json.JSONDecodeError:
                continue
        return {}

    @staticmethod
    def _normalize_assessment(payload: dict[str, Any]) -> dict[str, Any]:
        evidence = payload.get("evidence", [])
        if isinstance(evidence, str):
            evidence = [evidence]
        elif not isinstance(evidence, list):
            evidence = []

        # JSON null must read as empty, not the text "None", so the
        # empty-field check and the repair loop still apply.
        def text(value: Any) -> str:
            return "" if value is None else str(value).strip()

        return {
            "detected": OpenAIOpsAgent._coerce_bool(payload.get("detected")),
            "localized": OpenAIOpsAgent._coerce_bool(payload.get("localized")),
            "repaired": OpenAIOpsAgent._coerce_bool(payload.get("repaired")),
            "summary": text(payload.get("summary")),
            "root_cause": text(payload.get("root_cause")),
            "remediation": text(payload.get("remediation")),
            "evidence": [text(item) for item in evidence if text(item)],
        }

    @staticmethod
    def _validate_assessment(assessment: dict[str, Any]) -> str:
        if not assessment:
            return "Assessment is empty."
        required_fields = {
            "detected",
            "localized",
            "repaired",
            "summary",
            "root_cause",
            "remediation",
            "evidence",
        }
        missing = sorted(required_fields - set(assessment))
        if missing:
            return f"Assessment is missing fields: {', '.join(missing)}."
        if not isinstance(assessment["evidence"], list):
            return "Assessment evidence must be a list."
        if not assessment["summary"]:
            return "Assessment summary is empty."
        if not assessment["root_cause"]:
            return "Assessment root_cause is empty."
        if not assessment["remediation"]:
            return "Assessment remediation is empty."
        return ""

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        lowered = str(value).strip().lower()
        if lowered in {"true", "yes", "y", "1"}:
            return True
        if lowered in {"false", "no", "n", "0"}:
            return False
        return False
