"""Minimal NO_REPLY delivery reproduction."""

from __future__ import annotations

import re


_EXACT_SILENT_REPLY = re.compile(r"^\s*NO_REPLY\s*$", re.IGNORECASE)


def is_silent_reply_text(text: str) -> bool:
    """Return whether the text should be treated as a silent reply."""

    stripped = text.strip()
    if not stripped:
        return False
    return bool(_EXACT_SILENT_REPLY.match(stripped))


def sanitize_model_output(text: str) -> str:
    """Normalize model output before delivery."""

    if is_silent_reply_text(text):
        return ""
    return text.strip()


def should_deliver_model_output(text: str, stop_reason: str = "stop") -> bool:
    """Decide whether model output should be delivered to the user."""

    if not text.strip():
        return False
    if is_silent_reply_text(text):
        return False
    return True
