"""Shared Anthropic Messages API helpers for ACBench agents."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Statuses worth retrying: rate limits, server errors and "overloaded" (529).
_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


def anthropic_messages_create(
    *,
    api_key: str,
    model: str,
    prompt: str,
    base_url: str = "https://api.anthropic.com",
    version: str = "2023-06-01",
    max_tokens: int = 4096,
    timeout: float = 600.0,
    max_retries: int = 2,
    response_meta: dict[str, Any] | None = None,
) -> str:
    """Send one prompt to the Anthropic Messages API and return plain text.

    Transient failures are retried up to `max_retries` times with exponential
    backoff, matching the OpenAI SDK defaults. When `response_meta` is given it
    receives the reply's `stop_reason`, so callers can detect truncation.
    """

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }
    url = base_url.rstrip("/") + "/v1/messages"
    request = Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": version,
        },
        method="POST",
    )
    for attempt in range(max_retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            if exc.code in _RETRYABLE_STATUS and attempt < max_retries:
                time.sleep(0.5 * 2**attempt)
                continue
            raise ValueError(f"Anthropic API request failed with HTTP {exc.code}: {message}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt < max_retries:
                time.sleep(0.5 * 2**attempt)
                continue
            reason = getattr(exc, "reason", exc)
            raise ValueError(f"Anthropic API request failed: {reason}") from exc

    if response_meta is not None:
        response_meta["stop_reason"] = body.get("stop_reason")
    return extract_text_from_message(body)


def extract_text_from_message(body: dict[str, Any]) -> str:
    """Flatten Anthropic message content blocks into one text string."""

    parts: list[str] = []
    for block in body.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            text = str(block.get("text", ""))
            if text:
                parts.append(text)
    return "\n".join(parts).strip()
