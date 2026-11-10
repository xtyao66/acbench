"""Anthropic-backed code agent integrations for ACBench."""

from __future__ import annotations

import os
import json
from pathlib import Path
from time import perf_counter

from acbench.agents.anthropic_common import anthropic_messages_create
from acbench.agents.openai_code import OpenAICodePatchAgent
from acbench.agents.telemetry import summarize_call_records, timed_call
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec


class AnthropicCodePatchAgent(OpenAICodePatchAgent):
    """Generate a unified diff patch with Claude via the Anthropic Messages API."""

    def generate_patch(
        self,
        scenario: ScenarioSpec,
        run_config: RunConfig,
        *,
        output_dir: Path,
    ) -> dict[str, str]:
        section = dict(run_config.code_agent_config or {})
        model = str(section.get("model", run_config.anthropic_model)).strip()
        api_key_env = str(
            section.get(
                "api_key_env",
                run_config.anthropic_api_key_env or "ANTHROPIC_API_KEY",
            )
        ).strip()
        base_url = str(
            section.get(
                "base_url",
                run_config.anthropic_base_url or "https://api.anthropic.com",
            )
        ).strip()
        version = str(
            section.get(
                "version",
                run_config.anthropic_version or "2023-06-01",
            )
        ).strip()
        max_tokens = int(section.get("max_tokens", 4096))

        api_key = os.environ.get(
            api_key_env or "ANTHROPIC_API_KEY",
            "",
        )
        if not api_key:
            raise ValueError(
                f"Environment variable `{api_key_env}` is not set."
            )
        if not model:
            raise ValueError(
                "RunConfig.anthropic_model is required for AnthropicCodePatchAgent."
            )

        prompt = self._build_prompt(scenario, run_config)
        prompt_path = output_dir / "anthropic_prompt.txt"
        response_path = output_dir / "anthropic_response.txt"
        telemetry_path = output_dir / "anthropic_code_telemetry.json"
        prompt_path.write_text(prompt, encoding="utf-8")

        started = perf_counter()
        call_records: list[dict[str, object]] = []
        raw_text, call_record = timed_call(
            "initial_answer",
            anthropic_messages_create,
            api_key=api_key,
            model=model,
            prompt=prompt,
            base_url=base_url or "https://api.anthropic.com",
            version=version or "2023-06-01",
            max_tokens=max_tokens,
            response_meta=(meta := {}),
        )
        call_record["truncated"] = meta.get("stop_reason") == "max_tokens"
        call_records.append(call_record)
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
            repair_text, call_record = timed_call(
                f"repair_answer_{len(call_records)}",
                anthropic_messages_create,
                api_key=api_key,
                model=model,
                prompt=repair_prompt,
                base_url=base_url or "https://api.anthropic.com",
                version=version or "2023-06-01",
                max_tokens=max_tokens,
                response_meta=(meta := {}),
            )
            call_record["truncated"] = meta.get("stop_reason") == "max_tokens"
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
            raise ValueError(
                f"Model returned an invalid unified diff after retries: {validation_error}"
            )

        patch_path = output_dir / "anthropic_generated_patch.diff"
        patch_path.write_text(patch_text, encoding="utf-8")
        return {
            "patch_text": patch_text,
            "prompt_path": str(prompt_path),
            "response_path": str(response_path),
            "generated_patch_path": str(patch_path),
            "telemetry": telemetry,
            "telemetry_path": str(telemetry_path),
        }
