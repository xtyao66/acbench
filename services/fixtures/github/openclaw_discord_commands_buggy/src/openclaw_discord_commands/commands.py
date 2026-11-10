"""Minimal Discord slash-command reproduction."""

from __future__ import annotations


NATIVE_RESPONSES = {
    "/status": "STATUS CARD",
    "/help": "HELP CARD",
}


def match_plugin_command(prompt: str) -> str | None:
    """Return a plugin command match when one exists."""

    if prompt in {"/status", "/help", "/plugins"}:
        return prompt
    return None


def execute_plugin_command(prompt: str) -> dict[str, object]:
    """Return the plugin-command result."""

    if prompt == "/plugins":
        return {"renderable": True, "text": "PLUGIN LIST"}
    return {"renderable": False, "text": ""}


def execute_native_command(prompt: str) -> str:
    """Return the native interaction response."""

    return NATIVE_RESPONSES[prompt]


def dispatch_discord_command(prompt: str, is_native_interaction: bool) -> str:
    """Dispatch one Discord command."""

    plugin_match = match_plugin_command(prompt)
    if plugin_match is not None:
        plugin_reply = execute_plugin_command(plugin_match)
        if not plugin_reply["renderable"]:
            return "Done."
        return str(plugin_reply["text"])

    if is_native_interaction and prompt in NATIVE_RESPONSES:
        return execute_native_command(prompt)

    return prompt
