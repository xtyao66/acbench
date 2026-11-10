"""Tests for the localized prompt-overlay reproduction."""

from __future__ import annotations

import unittest

from openclaw_prompt_overlay.overlay import (
    GPT5_OVERLAY,
    resolve_system_prompt_contribution,
)


class PromptOverlayTests(unittest.TestCase):
    def test_direct_openai_gpt5_models_keep_the_overlay(self) -> None:
        self.assertEqual(
            resolve_system_prompt_contribution("openai", "gpt-5.4"),
            GPT5_OVERLAY,
        )

    def test_non_gpt5_models_do_not_get_the_overlay(self) -> None:
        self.assertIsNone(
            resolve_system_prompt_contribution("openai", "gpt-4.1-mini")
        )

    def test_openrouter_prefixed_gpt5_models_also_get_the_overlay(self) -> None:
        self.assertEqual(
            resolve_system_prompt_contribution("openrouter", "openai/gpt-5.4"),
            GPT5_OVERLAY,
        )


if __name__ == "__main__":
    unittest.main()
