"""Tests for the localized MiniMax usage reproduction."""

from __future__ import annotations

import unittest

from openclaw_minimax_usage.usage import build_minimax_usage_request


class MinimaxUsageRequestTests(unittest.TestCase):
    def test_request_targets_the_expected_endpoint(self) -> None:
        request = build_minimax_usage_request("demo-key")
        self.assertEqual(
            request["url"],
            "https://api.minimax.io/v1/api/openplatform/coding_plan/remains",
        )

    def test_request_includes_bearer_auth_header(self) -> None:
        request = build_minimax_usage_request("demo-key")
        self.assertEqual(
            request["headers"]["Authorization"],
            "Bearer demo-key",
        )

    def test_request_uses_get_for_remains_endpoint(self) -> None:
        request = build_minimax_usage_request("demo-key")
        self.assertEqual(request["method"], "GET")


if __name__ == "__main__":
    unittest.main()
