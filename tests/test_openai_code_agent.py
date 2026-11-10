"""Tests for the OpenAI code patch agent helpers."""

from __future__ import annotations

import unittest

from acbench.agents.openai_code import OpenAICodePatchAgent


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
        return _FakeChatResponse("chat patch")


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeChatCompletions()


class _FakeChatClient:
    def __init__(self) -> None:
        self.chat = _FakeChat()


class OpenAICodePatchAgentTests(unittest.TestCase):
    def test_extract_patch_accepts_fenced_plain_unified_diff(self) -> None:
        response = """
Here is the fix.

```diff
--- a/src/example.py
+++ b/src/example.py
@@ -1,1 +1,1 @@
-return 1
+return 2
```

This should resolve the issue.
"""
        patch = OpenAICodePatchAgent._extract_patch(response)

        self.assertTrue(patch.startswith("--- a/src/example.py"))
        self.assertIn("@@ -1,1 +1,1 @@", patch)

    def test_extract_patch_trims_prose_around_non_fenced_diff(self) -> None:
        response = """
I fixed the bug below.
--- a/src/example.py
+++ b/src/example.py
@@ -1,1 +1,1 @@
-return 1
+return 2
Thanks!
"""
        patch = OpenAICodePatchAgent._extract_patch(response)

        self.assertNotIn("I fixed the bug below.", patch)
        self.assertNotIn("Thanks!", patch)
        self.assertTrue(patch.startswith("--- a/src/example.py"))

    def test_validate_unified_diff_accepts_plain_unified_diff(self) -> None:
        patch = "\n".join(
            [
                "--- a/src/example.py",
                "+++ b/src/example.py",
                "@@ -1,1 +1,1 @@",
                "-return 1",
                "+return 2",
            ]
        )

        self.assertEqual(OpenAICodePatchAgent._validate_unified_diff(patch), "")

    def test_extract_patch_converts_file_block_format(self) -> None:
        response = """
--- FILE: src/example.py ---
@@ -1,1 +1,1 @@
-return 1
+return 2
"""
        patch = OpenAICodePatchAgent._extract_patch(response)

        self.assertTrue(patch.startswith("--- a/src/example.py"))
        self.assertIn("+++ b/src/example.py", patch)

    def test_validate_unified_diff_accepts_semantic_hunk_headers(self) -> None:
        patch = "\n".join(
            [
                "--- a/src/example.py",
                "+++ b/src/example.py",
                "@@ def example(",
                "-return 1",
                "+return 2",
            ]
        )

        self.assertEqual(OpenAICodePatchAgent._validate_unified_diff(patch), "")

    def test_generate_text_supports_chat_completions_mode(self) -> None:
        client = _FakeChatClient()

        text, call_record = OpenAICodePatchAgent._generate_text(
            client,
            "chat_completions",
            label="chat_answer",
            model="deployment-name",
            prompt="return a patch",
        )

        self.assertEqual(text, "chat patch")
        self.assertEqual(call_record["label"], "chat_answer")
        self.assertEqual(
            client.chat.completions.last_kwargs["messages"],
            [{"role": "user", "content": "return a patch"}],
        )


if __name__ == "__main__":
    unittest.main()
