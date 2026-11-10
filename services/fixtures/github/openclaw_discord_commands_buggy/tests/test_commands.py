"""Tests for the localized Discord command reproduction."""

from __future__ import annotations

import unittest

from openclaw_discord_commands.commands import dispatch_discord_command


class DiscordCommandDispatchTests(unittest.TestCase):
    def test_native_status_interaction_returns_status_card(self) -> None:
        self.assertEqual(
            dispatch_discord_command("/status", is_native_interaction=True),
            "STATUS CARD",
        )

    def test_plugin_commands_still_render_on_the_text_path(self) -> None:
        self.assertEqual(
            dispatch_discord_command("/plugins", is_native_interaction=False),
            "PLUGIN LIST",
        )

    def test_unknown_text_messages_pass_through(self) -> None:
        self.assertEqual(
            dispatch_discord_command("hello openclaw", is_native_interaction=False),
            "hello openclaw",
        )


if __name__ == "__main__":
    unittest.main()
