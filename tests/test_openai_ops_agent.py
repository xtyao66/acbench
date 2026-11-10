"""Tests for the OpenAI-backed ops assessment agent."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acbench.agents.openai_ops import OpenAIOpsAgent
from acbench.executors.backends.ops.runtime import NativeOpsProblem
from acbench.models.runtime import RunConfig


class _FakeResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeChatResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeChatCompletions:
    def __init__(self) -> None:
        self.last_kwargs = {}

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeChatResponse("chat assessment")


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeChatCompletions()


class _FakeChatClient:
    def __init__(self) -> None:
        self.chat = _FakeChat()


class _FakeClient:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.responses = self

    def create(self, **kwargs):
        if not self._outputs:
            raise AssertionError("Fake client received more requests than expected.")
        return _FakeResponse(self._outputs.pop(0))


class OpenAIOpsAgentTests(unittest.TestCase):
    def test_agent_configures_from_run_config(self) -> None:
        agent = OpenAIOpsAgent()
        agent.configure(
            RunConfig(
                openai_model="gpt-test",
                openai_api_key_env="TEST_OPENAI_KEY",
                openai_base_url="https://example.invalid/v1",
            )
        )
        self.assertEqual(agent.model, "gpt-test")
        self.assertEqual(agent.api_key_env, "TEST_OPENAI_KEY")
        self.assertEqual(agent.base_url, "https://example.invalid/v1")

    def test_agent_extracts_plain_json_assessment(self) -> None:
        response = json.dumps(
            {
                "detected": True,
                "localized": True,
                "repaired": False,
                "summary": "Queue backlog detected.",
                "root_cause": "The worker tier is throttled.",
                "remediation": "Restart or scale the worker tier.",
                "evidence": ["consumer lag rose sharply"],
            }
        )
        assessment = OpenAIOpsAgent._extract_assessment(response)
        self.assertTrue(assessment["detected"])
        self.assertEqual(assessment["evidence"], ["consumer lag rose sharply"])

    def test_agent_extracts_fenced_json_assessment(self) -> None:
        response = """
The answer is below.
```json
{
  "detected": true,
  "localized": true,
  "repaired": true,
  "summary": "Health check is falsely marking the service unhealthy.",
  "root_cause": "The node fetch healthcheck exits before the request settles.",
  "remediation": "Use a blocking curl or await fetch in the healthcheck command.",
  "evidence": ["docker ps shows unhealthy", "curl /healthz returns 200"]
}
```
"""
        assessment = OpenAIOpsAgent._extract_assessment(response)
        self.assertTrue(assessment["localized"])
        self.assertIn("curl /healthz returns 200", assessment["evidence"])

    def test_agent_analyze_writes_prompt_response_and_assessment(self) -> None:
        agent = OpenAIOpsAgent()
        agent.configure(RunConfig(openai_model="gpt-test"))
        problem = NativeOpsProblem(
            problem_id="ops-1",
            source="acbench",
            application="queue-worker",
            service="notification-consumer",
            task_summary="Triage a backlog incident.",
            task_instructions="Use the evidence and return a structured answer.",
            issue_text="Queue backlog spiked.",
            require_detection=True,
            require_localization=True,
            require_repair=True,
        )
        response = json.dumps(
            {
                "detected": True,
                "localized": True,
                "repaired": True,
                "summary": "The backlog incident is real.",
                "root_cause": "The worker tier is stuck.",
                "remediation": "Restart the worker and increase concurrency.",
                "evidence": ["consumer lag rose from 12s to 540s"],
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
                with patch(
                    "acbench.agents.openai_ops.OpenAI",
                    return_value=_FakeClient([response]),
                ):
                    artifacts = agent.analyze(problem, output_dir=Path(tmp_dir))

            self.assertTrue(Path(artifacts["prompt_path"]).exists())
            self.assertTrue(Path(artifacts["response_path"]).exists())
            self.assertTrue(Path(artifacts["assessment_path"]).exists())
            self.assertTrue(artifacts["assessment"]["repaired"])
            self.assertEqual(artifacts["telemetry"]["answer_count"], 1)
            self.assertEqual(len(artifacts["telemetry"]["answer_durations_seconds"]), 1)
            self.assertTrue(Path(artifacts["telemetry_path"]).exists())
            self.assertIn("structured answer", agent.last_prompt)
            self.assertIn("Restart the worker", agent.last_response)
            self.assertTrue(agent.last_assessment["detected"])

    def test_agent_repairs_invalid_json_response(self) -> None:
        agent = OpenAIOpsAgent()
        agent.configure(RunConfig(openai_model="gpt-test"))
        problem = NativeOpsProblem(
            problem_id="ops-2",
            source="acbench",
            application="cache-api",
            service="search-index",
            task_summary="Triage stale index incident.",
            task_instructions="Return JSON only.",
            issue_text="Search results are stale.",
            require_detection=True,
        )
        fixed = json.dumps(
            {
                "detected": True,
                "localized": True,
                "repaired": True,
                "summary": "The index is stale.",
                "root_cause": "The indexing path is lagging.",
                "remediation": "Reindex and refresh the cache.",
                "evidence": ["freshness lag exceeded the SLO"],
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
                with patch(
                    "acbench.agents.openai_ops.OpenAI",
                    return_value=_FakeClient(["not json", fixed]),
                ):
                    artifacts = agent.analyze(problem, output_dir=Path(tmp_dir))

        self.assertTrue(artifacts["assessment"]["detected"])
        self.assertIn("ASSESSMENT REPAIR", agent.last_response)

    def test_generate_text_supports_chat_completions_mode(self) -> None:
        client = _FakeChatClient()

        text, call_record = OpenAIOpsAgent._generate_text(
            client,
            "chat_completions",
            label="chat_answer",
            model="deployment-name",
            prompt="return json",
        )

        self.assertEqual(text, "chat assessment")
        self.assertEqual(call_record["label"], "chat_answer")
        self.assertEqual(
            client.chat.completions.last_kwargs["messages"],
            [{"role": "user", "content": "return json"}],
        )


class FakeOpsAssessmentAgent:
    """Tiny fake ops agent for executor and engine tests."""

    def configure(self, **kwargs) -> None:
        self.config = kwargs

    def analyze(self, problem, *, output_dir: Path) -> dict[str, object]:
        output_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = output_dir / "fake_prompt.txt"
        response_path = output_dir / "fake_response.txt"
        assessment_path = output_dir / "fake_assessment.json"
        telemetry_path = output_dir / "fake_ops_telemetry.json"
        prompt_path.write_text("fake prompt", encoding="utf-8")
        response_path.write_text("fake response", encoding="utf-8")
        # Simulate a *correct* agent: surface every expected diagnosis keyword in
        # the section the rubric grades it against, so a genuinely-right answer
        # clears the leakage-aware recall threshold.
        detection = ", ".join(problem.detection_keywords) or "incident"
        localization = ", ".join(problem.localization_keywords) or problem.service or "service"
        remediation = ", ".join(problem.repair_keywords) or "fix"
        assessment = {
            "detected": True,
            "localized": True,
            "repaired": True,
            "summary": f"{problem.application} incident detected: {detection}",
            "root_cause": f"{problem.service} root cause localized to {localization}",
            "remediation": f"Apply remediation: {remediation}",
            "evidence": list(problem.error_logs or ["synthetic evidence"]) + list(problem.detection_keywords),
        }
        assessment_path.write_text(json.dumps(assessment), encoding="utf-8")
        telemetry = {
            "answer_count": 1,
            "answer_durations_seconds": [0.25],
            "total_answer_seconds": 0.25,
            "average_answer_seconds": 0.25,
            "wall_time_seconds": 0.3,
            "answer_labels": ["initial_answer"],
        }
        telemetry_path.write_text(json.dumps(telemetry), encoding="utf-8")
        return {
            "assessment": assessment,
            "prompt_path": str(prompt_path),
            "response_path": str(response_path),
            "assessment_path": str(assessment_path),
            "telemetry": telemetry,
            "telemetry_path": str(telemetry_path),
        }


if __name__ == "__main__":
    unittest.main()
