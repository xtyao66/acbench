"""Request-routing resolver.

The ingress gateway receives a stream of inbound requests and, for each one,
must look up which backend pool the request's route should be dispatched to and
build the request's effective routing policy (retry schedule, normalized
headers, shadow targets). The routing table lives in a serialized JSON config
document (see ``config_blob.RAW_CONFIG``): plain JSON *text* that has to be
deserialized into Python objects before any route can be read out of it.

``RouteResolver`` answers ``resolve(path)`` -- returning the backend pool for a
route -- and ``resolve_policy(path)`` -- returning the fully normalized
effective policy -- for each request. It also exposes ``parse_count`` (the
number of times it has deserialized the config document) so a regression test
can assert the *parsing cost* of a batch of lookups deterministically, with no
wall-clock timing.
"""

from __future__ import annotations

import json


class RouteResolver:
    """Resolve request paths to backends/policies from a serialized config blob.

    The resolver is constructed from the raw JSON config *text*. Building the
    effective policy for a request is genuine per-request work (normalizing
    headers, expanding the retry schedule) that every implementation must do.
    This fixture's *inefficiency* is separate: it re-deserializes the entire
    config document from scratch on every single call before doing that work.
    """

    def __init__(self, raw_config: str) -> None:
        # The serialized JSON config document, kept as text. The buggy resolver
        # re-parses this string from scratch on every call below.
        self._raw_config = raw_config
        # Number of times the config document has been deserialized. A counting
        # oracle uses this to distinguish "parse once" from "parse per call".
        self.parse_count = 0

    def _load_config(self) -> dict:
        """Deserialize the config document.

        This is the expensive, *repeated* step: ``json.loads`` walks the entire
        JSON text and rebuilds every route object. The buggy resolver invokes
        this on every request instead of parsing once and caching the result.
        """

        self.parse_count += 1
        return json.loads(self._raw_config)

    @staticmethod
    def _effective_policy(config: dict, entry: dict) -> dict:
        """Build the normalized effective routing policy for a matched route.

        Genuine per-request work, independent of the parsing inefficiency:
        expand the retry backoff schedule, merge and normalize headers over the
        config defaults, and canonicalize shadow targets. Every correct
        implementation -- parse-per-call or parse-once -- performs this step.
        """

        retry = entry["retry_policy"]
        schedule = []
        cumulative = 0
        retry_on = tuple(sorted(retry["retry_on"]))
        for attempt in range(retry["max_attempts"]):
            backoff = retry["backoff_ms"][attempt % len(retry["backoff_ms"])]
            cumulative += backoff
            schedule.append((attempt, backoff, cumulative, retry_on))

        headers = dict(config.get("default_headers", {}))
        for key, value in entry["headers"].items():
            headers[key.strip().lower()] = value.strip()
        normalized_headers = tuple(sorted(headers.items()))

        shadows = tuple(sorted({s.lower() for s in entry["shadow_targets"]}))
        cache_key = "|".join(f"{k}={v}" for k, v in normalized_headers)

        return {
            "backend_pool": entry["backend_pool"],
            "timeout_ms": entry["timeout_ms"],
            "retry_schedule": tuple(schedule),
            "headers": normalized_headers,
            "shadow_targets": shadows,
            "cache_key_len": len(cache_key),
        }

    def resolve_policy(self, path: str) -> dict | None:
        """Return the effective policy for ``path`` (or ``None`` for unknowns).

        Re-parses the full routing-config document on every call (via
        ``_load_config``), then builds the effective policy for the matched
        route. For a stream of N requests this deserializes the whole document N
        times -- the parsing cost is paid per request instead of once.
        """

        config = self._load_config()
        entry = config["routes"].get(path)
        if entry is None:
            return None
        return self._effective_policy(config, entry)

    def resolve(self, path: str) -> str:
        """Return the backend pool for ``path`` (or the default for unknowns)."""

        policy = self.resolve_policy(path)
        if policy is None:
            # Unknown route: re-load is unavoidable here too, mirroring the per
            # call parse; fall back to the configured default backend.
            return json.loads(self._raw_config)["default_backend"]
        return policy["backend_pool"]
