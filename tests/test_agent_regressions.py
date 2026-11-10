"""Regression tests for patch handling and provider quirks in the model-backed agents."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from acbench.agents.anthropic_common import anthropic_messages_create
from acbench.agents.anthropic_ops import AnthropicOpsAgent
from acbench.agents.azure_openai_ops import AzureOpenAIOpsAgent
from acbench.agents.openai_code import TRUNCATED_RESPONSE_ERROR, OpenAICodePatchAgent
from acbench.agents.openai_ops import OpenAIOpsAgent
from acbench.models.runtime import RunConfig

Agent = OpenAICodePatchAgent

# A fix to two functions with a blank context line between them, written as an
# empty line rather than a single space (git apply accepts this).
BLANK_CONTEXT_DIFF = "\n".join(
    [
        "--- a/src/m.py",
        "+++ b/src/m.py",
        "@@ -1,5 +1,5 @@",
        " def f():",
        "-    return 1",
        "+    return 2",
        "",
        " def g():",
        "-    return 3",
        "+    return 4",
    ]
)

TWO_FILE_PLAIN_DIFF = "\n".join(
    [
        "--- a/src/a.py",
        "+++ b/src/a.py",
        "@@ -1,2 +1,2 @@",
        "-x = 1",
        "+x = 2",
        " y = 1",
        "--- a/src/b.py",
        "+++ b/src/b.py",
        "@@ -1,1 +1,1 @@",
        "-z = 1",
        "+z = 2",
    ]
)


def _pipeline(response: str) -> str:
    return Agent._normalize_unified_diff(Agent._extract_patch(response))


class PatchPipelineRegressionTests(unittest.TestCase):
    def test_unfenced_blank_context_line_keeps_the_whole_hunk(self) -> None:
        patch_text = _pipeline(BLANK_CONTEXT_DIFF + "\n\nThis fixes both functions.")

        self.assertIn("@@ -1,5 +1,5 @@", patch_text)
        self.assertIn("+    return 4", patch_text)
        self.assertNotIn("This fixes", patch_text)
        self.assertEqual(Agent._validate_unified_diff(patch_text), "")

    def test_fenced_blank_context_line_validates(self) -> None:
        patch_text = _pipeline(f"```diff\n{BLANK_CONTEXT_DIFF}\n```")

        self.assertIn("+    return 4", patch_text)
        self.assertEqual(Agent._validate_unified_diff(patch_text), "")

    def test_normalizer_keeps_plain_multi_file_headers_out_of_hunks(self) -> None:
        patch_text = Agent._normalize_unified_diff(TWO_FILE_PLAIN_DIFF)

        self.assertIn("@@ -1,2 +1,2 @@\n-x = 1\n+x = 2\n y = 1\n--- a/src/b.py", patch_text)
        self.assertIn("@@ -1,1 +1,1 @@\n-z = 1\n+z = 2", patch_text)
        self.assertEqual(Agent._validate_unified_diff(patch_text), "")

    def test_separator_blank_lines_between_file_sections_are_dropped(self) -> None:
        first, second = TWO_FILE_PLAIN_DIFF.split("--- a/src/b.py")
        response = f"{first}\n--- a/src/b.py{second}"

        patch_text = _pipeline(response)

        self.assertIn("+++ b/src/b.py", patch_text)
        self.assertNotIn("\n\n", patch_text)
        self.assertEqual(Agent._validate_unified_diff(patch_text), "")

    def test_one_fence_per_file_keeps_every_file(self) -> None:
        first, second = TWO_FILE_PLAIN_DIFF.split("--- a/src/b.py")
        response = f"```diff\n{first}```\n\nAnd:\n\n```diff\n--- a/src/b.py{second}\n```"

        patch_text = _pipeline(response)

        self.assertIn("+++ b/src/a.py", patch_text)
        self.assertIn("+++ b/src/b.py", patch_text)

    def test_repeated_fence_for_the_same_file_keeps_the_first(self) -> None:
        response = f"```diff\n{TWO_FILE_PLAIN_DIFF}\n```\n\n```diff\n{TWO_FILE_PLAIN_DIFF}\n```"

        self.assertEqual(Agent._extract_patch(response), TWO_FILE_PLAIN_DIFF)

    def test_trailing_bullet_list_is_not_pulled_into_the_patch(self) -> None:
        response = "\n".join(
            [
                "--- a/src/a.py",
                "+++ b/src/a.py",
                "@@ -1 +1 @@",
                "-x = 1",
                "+x = 2",
                "",
                "- changed x",
            ]
        )

        self.assertNotIn("changed", Agent._extract_patch(response))

    def test_overcounted_header_does_not_pull_in_trailing_bullets(self) -> None:
        response = "\n".join(
            [
                "--- a/src/app.py",
                "+++ b/src/app.py",
                "@@ -1,6 +1,6 @@",
                " import os",
                "-DEBUG = True",
                "+DEBUG = False",
                " LEVEL = 1",
                "",
                "- Turned off DEBUG",
                "- Kept LEVEL",
            ]
        )

        patch_text = _pipeline(response)

        self.assertNotIn("Turned off", patch_text)
        self.assertIn("@@ -1,3 +1,3 @@", patch_text)

    def test_optional_test_block_after_the_fix_is_not_merged(self) -> None:
        first, _ = TWO_FILE_PLAIN_DIFF.split("--- a/src/b.py")
        test_block = "--- a/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -1 +1 @@\n-t = 1\n+t = 2"
        response = f"```diff\n{first}```\n\nOptionally add a test:\n\n```diff\n{test_block}\n```"

        self.assertNotIn("tests/test_a.py", Agent._extract_patch(response))

    def test_repeated_block_with_other_path_prefixes_is_kept_once(self) -> None:
        repeated = TWO_FILE_PLAIN_DIFF.replace("+++ b/", "+++ ")
        response = f"```diff\n{TWO_FILE_PLAIN_DIFF}\n```\n\n```diff\n{repeated}\n```"

        self.assertEqual(Agent._extract_patch(response), TWO_FILE_PLAIN_DIFF)


class HiddenLocationDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="acbench-discover-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _touch(self, *relative_paths: str) -> None:
        for relative in relative_paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("package x\n", encoding="utf-8")

    def test_go_repository_without_src_lists_go_sources(self) -> None:
        self._touch("skl/skl.go", "skl/skl_test.go", "db.go", "vendor/v/v.go", ".git/x.go", "README.md")

        found = Agent._discover_default_targets(self.root, required=["skl/skl.go"], language="go")

        self.assertEqual(found, ["db.go", "skl/skl.go"])

    def test_required_files_survive_the_cap_and_order_is_by_path(self) -> None:
        self._touch(*(f"pkg/a{index:02d}.go" for index in range(15)), "zz/target.go")

        found = Agent._discover_default_targets(self.root, required=["zz/target.go"], limit=10)

        self.assertEqual(len(found), 10)
        self.assertIn("zz/target.go", found)
        self.assertEqual(found, sorted(found))

    def test_fault_file_sits_inside_a_contiguous_run_of_files(self) -> None:
        names = [f"src/pkg/mod{index:02d}.py" for index in range(30)]
        self._touch(*names)

        found = Agent._discover_default_targets(self.root, required=["src/pkg/mod23.py"], limit=10)

        self.assertIn("src/pkg/mod23.py", found)
        start = names.index(found[0])
        self.assertEqual(found, names[start : start + 10])

    def test_hidden_location_prompt_shows_source_for_go_scenarios(self) -> None:
        self._touch("skl/skl.go")
        scenario = SimpleNamespace(
            scenario_id="perf_x",
            title="t",
            notes="n",
            build=SimpleNamespace(language="go", rebuild_cmds=[], test_cmds=[]),
            code_fault=SimpleNamespace(target_files=["skl/skl.go"]),
        )
        run_config = RunConfig(hide_fault_location=True)

        prompt = Agent()._build_repository_prompt(scenario, self.root, run_config)

        self.assertIn("--- FILE: skl/skl.go ---", prompt)


class TruncationTests(unittest.TestCase):
    def test_truncated_reply_is_a_patch_error_even_when_the_diff_validates(self) -> None:
        patch_text = Agent._normalize_unified_diff(BLANK_CONTEXT_DIFF)

        self.assertEqual(Agent._patch_error(patch_text, {"truncated": False}), "")
        self.assertEqual(Agent._patch_error(patch_text, {"truncated": True}), TRUNCATED_RESPONSE_ERROR)

    def test_detects_truncation_in_both_openai_response_shapes(self) -> None:
        self.assertTrue(Agent._response_truncated(SimpleNamespace(status="incomplete")))
        self.assertTrue(
            Agent._response_truncated(SimpleNamespace(choices=[SimpleNamespace(finish_reason="length")]))
        )
        self.assertFalse(
            Agent._response_truncated(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")]))
        )


class _FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class AnthropicTransportTests(unittest.TestCase):
    def _body(self, stop_reason: str) -> _FakeHTTPResponse:
        payload = {"content": [{"type": "text", "text": "hi"}], "stop_reason": stop_reason}
        return _FakeHTTPResponse(json.dumps(payload).encode("utf-8"))

    def test_reports_stop_reason_and_passes_a_timeout(self) -> None:
        meta: dict = {}
        with patch("acbench.agents.anthropic_common.urlopen", return_value=self._body("max_tokens")) as opened:
            text = anthropic_messages_create(api_key="k", model="m", prompt="p", response_meta=meta)

        self.assertEqual(text, "hi")
        self.assertEqual(meta["stop_reason"], "max_tokens")
        self.assertEqual(opened.call_args.kwargs["timeout"], 600.0)

    def test_retries_overloaded_responses(self) -> None:
        overloaded = HTTPError("u", 529, "overloaded", {}, io.BytesIO(b"{}"))
        responses = [overloaded, self._body("end_turn")]

        def fake_urlopen(request, timeout):
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch("acbench.agents.anthropic_common.urlopen", side_effect=fake_urlopen), patch(
            "acbench.agents.anthropic_common.time.sleep"
        ):
            self.assertEqual(anthropic_messages_create(api_key="k", model="m", prompt="p"), "hi")

    def test_client_errors_are_not_retried(self) -> None:
        bad_request = HTTPError("u", 400, "bad", {}, io.BytesIO(b"bad request"))
        with patch("acbench.agents.anthropic_common.urlopen", side_effect=bad_request) as opened:
            with self.assertRaisesRegex(ValueError, "HTTP 400"):
                anthropic_messages_create(api_key="k", model="m", prompt="p")
        self.assertEqual(opened.call_count, 1)


class OpsAssessmentTests(unittest.TestCase):
    def test_json_null_fields_read_as_empty_and_fail_validation(self) -> None:
        payload = {
            "detected": True,
            "localized": True,
            "repaired": True,
            "summary": "s",
            "root_cause": None,
            "remediation": None,
            "evidence": [None, "log line"],
        }
        for agent in (OpenAIOpsAgent, AnthropicOpsAgent):
            with self.subTest(agent=agent.__name__):
                assessment = agent._normalize_assessment(payload)
                self.assertEqual(assessment["root_cause"], "")
                self.assertEqual(assessment["evidence"], ["log line"])
                self.assertNotEqual(agent._validate_assessment(assessment), "")

    def test_azure_ops_agent_defaults_to_the_azure_key_env(self) -> None:
        agent = AzureOpenAIOpsAgent()
        agent.configure(
            RunConfig(
                ops_agent_config={
                    "model": "deployment",
                    "base_url": "https://example.openai.azure.com/openai/v1/",
                    "api": "chat_completions",
                }
            )
        )

        self.assertEqual(agent.api_key_env, "AZURE_OPENAI_API_KEY")
        self.assertEqual(agent.model, "deployment")
        self.assertEqual(agent.api_mode, "chat_completions")


if __name__ == "__main__":
    unittest.main()
