"""Tests for the localized NO_REPLY reproduction."""

from __future__ import annotations

import unittest

from openclaw_no_reply.tokens import sanitize_model_output, should_deliver_model_output


class SilentReplyDetectionTests(unittest.TestCase):
    def test_exact_no_reply_is_suppressed(self) -> None:
        self.assertFalse(should_deliver_model_output("NO_REPLY"))
        self.assertEqual(sanitize_model_output("NO_REPLY"), "")

    def test_normal_visible_text_is_delivered(self) -> None:
        self.assertTrue(should_deliver_model_output("hello from openclaw"))
        self.assertEqual(
            sanitize_model_output("hello from openclaw"),
            "hello from openclaw",
        )

    def test_no_reply_prefix_with_trailing_text_is_also_suppressed(self) -> None:
        leaked = "NO_REPLYThe user is still thinking through the command"
        self.assertFalse(should_deliver_model_output(leaked))
        self.assertEqual(sanitize_model_output(leaked), "")


if __name__ == "__main__":
    unittest.main()
