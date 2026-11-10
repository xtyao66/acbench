"""Minimal MiniMax usage-request reproduction."""

from __future__ import annotations


def build_minimax_usage_request(api_key: str) -> dict[str, object]:
    """Build the request OpenClaw would send to the MiniMax usage endpoint."""

    return {
        "method": "POST",
        "url": "https://api.minimax.io/v1/api/openplatform/coding_plan/remains",
        "headers": {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    }
