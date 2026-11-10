"""Tests for the request-routing resolver.

``test_resolve_parses_config_once`` is the performance oracle: it counts how
many times the resolver deserializes the config document (no wall-clock timing)
and fails on the parse-per-call implementation, whose parsing cost grows with
the number of lookups. The correctness tests pin the resolved backends *and* the
fully normalized effective policy so a fast-but-wrong patch (e.g. skipping the
lookup, returning a constant, or short-circuiting the per-request normalization)
cannot earn credit by changing behavior.
"""

from __future__ import annotations

import json
import unittest

from route_config.resolver import RouteResolver


def _entry(pool, max_attempts, headers, shadows, timeout_ms=300):
    return {
        "backend_pool": pool,
        "weight": 10,
        "timeout_ms": timeout_ms,
        "retry_policy": {
            "max_attempts": max_attempts,
            "backoff_ms": [50, 100, 200, 400][:max_attempts],
            "retry_on": ["504", "503", "connect-failure"],
        },
        "headers": headers,
        "shadow_targets": shadows,
    }


def _make_config() -> str:
    """A small, fully-known routing config serialized to JSON text."""

    return json.dumps(
        {
            "version": "test-snapshot",
            "default_backend": "pool-default",
            "default_headers": {"x-default-0": "d0", "x-default-1": "d1"},
            "routes": {
                "/api/v0/users": _entry(
                    "pool-users",
                    2,
                    {"X-Route-Tag-0": " alpha ", "x-route-tag-1": "beta"},
                    ["Shadow-B", "shadow-a", "shadow-b"],
                    timeout_ms=250,
                ),
                "/api/v0/orders": _entry(
                    "pool-orders",
                    3,
                    {"x-route-tag-0": "gamma"},
                    ["shadow-c"],
                    timeout_ms=500,
                ),
                "/api/v1/billing": _entry(
                    "pool-billing",
                    1,
                    {"X-ROUTE-TAG-9": "delta"},
                    ["shadow-d", "shadow-d"],
                    timeout_ms=750,
                ),
            },
        }
    )


# Number of lookups for the performance oracle. Large enough that a
# parse-per-call implementation deserializes the document many times while a
# parse-once implementation deserializes it at most a small constant number of
# times.
_LOOKUP_COUNT = 200


class RouteResolverTests(unittest.TestCase):
    def test_resolve_parses_config_once(self) -> None:
        resolver = RouteResolver(_make_config())
        for _ in range(_LOOKUP_COUNT):
            resolver.resolve("/api/v0/users")
        # Performance oracle: resolving N requests must deserialize the config
        # document a small constant number of times, NOT once per request. A
        # parse-per-call resolver parses it _LOOKUP_COUNT times; a parse-once
        # resolver parses it at most a couple of times (construction / first
        # use). Allow a tiny constant for lazy initialization.
        self.assertLessEqual(resolver.parse_count, 2)

    def test_resolves_known_routes_to_backends(self) -> None:
        resolver = RouteResolver(_make_config())
        # Correctness: each known route maps to its configured backend pool.
        self.assertEqual(resolver.resolve("/api/v0/users"), "pool-users")
        self.assertEqual(resolver.resolve("/api/v0/orders"), "pool-orders")
        self.assertEqual(resolver.resolve("/api/v1/billing"), "pool-billing")

    def test_unknown_route_falls_back_to_default(self) -> None:
        resolver = RouteResolver(_make_config())
        # Edge case: an unknown route resolves to the configured default
        # backend, not to a known pool and not to an error. resolve_policy
        # reports the miss as None.
        self.assertEqual(
            resolver.resolve("/api/v2/not-configured"), "pool-default"
        )
        self.assertEqual(resolver.resolve(""), "pool-default")
        self.assertIsNone(resolver.resolve_policy("/api/v2/not-configured"))

    def test_effective_policy_is_fully_normalized(self) -> None:
        resolver = RouteResolver(_make_config())
        policy = resolver.resolve_policy("/api/v0/users")
        # Correctness of the per-request work that a parse-once fix must keep:
        # the retry schedule is expanded with cumulative backoff, headers are
        # lower-cased/stripped and merged over the config defaults, and shadow
        # targets are de-duplicated, lower-cased, and sorted.
        self.assertEqual(policy["backend_pool"], "pool-users")
        self.assertEqual(policy["timeout_ms"], 250)
        self.assertEqual(
            policy["retry_schedule"],
            (
                (0, 50, 50, ("503", "504", "connect-failure")),
                (1, 100, 150, ("503", "504", "connect-failure")),
            ),
        )
        self.assertEqual(
            policy["headers"],
            (
                ("x-default-0", "d0"),
                ("x-default-1", "d1"),
                ("x-route-tag-0", "alpha"),
                ("x-route-tag-1", "beta"),
            ),
        )
        self.assertEqual(policy["shadow_targets"], ("shadow-a", "shadow-b"))

    def test_repeated_and_mixed_lookups_are_stable(self) -> None:
        resolver = RouteResolver(_make_config())
        # Edge case: repeated and interleaved lookups (including unknowns) keep
        # returning the same backend for the same path -- caching the parsed
        # config must not corrupt or mutate the routing table between calls.
        sequence = [
            "/api/v0/users",
            "/api/v0/users",
            "/api/v9/unknown",
            "/api/v1/billing",
            "/api/v0/users",
            "/api/v9/unknown",
            "/api/v0/orders",
        ]
        expected = [
            "pool-users",
            "pool-users",
            "pool-default",
            "pool-billing",
            "pool-users",
            "pool-default",
            "pool-orders",
        ]
        self.assertEqual([resolver.resolve(p) for p in sequence], expected)
        # And the resolved policy for a repeated path is identical each time.
        first = resolver.resolve_policy("/api/v0/orders")
        second = resolver.resolve_policy("/api/v0/orders")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
