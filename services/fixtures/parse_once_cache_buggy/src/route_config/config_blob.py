"""In-repo generator for a realistic routing-config JSON blob.

This stands in for the serialized routing configuration a gateway loads from a
config service or a mounted file: a single JSON document mapping each route to
the backend pool, retry policy, headers, and shadow targets it should be
dispatched with. The blob is real JSON text whose deserialization
(``json.loads``) is genuine, non-trivial CPU work -- the cost an ingress worker
pays if it re-parses the document on every request instead of parsing it once
and caching the result.

``RAW_CONFIG`` is the serialized JSON text (a ``str``). Resolving a route from
it requires deserializing the text back into Python objects first; the whole
point of the fixture is that this deserialization is the hot, repeated cost.
"""

from __future__ import annotations

import json

# Number of route entries in the routing table. Each entry carries a backend
# pool, retry policy, a header bag, and shadow targets, so the serialized
# document is a few KB of real JSON whose ``json.loads`` is genuine CPU work.
_ROUTE_COUNT = 12


def _build_config_object() -> dict[str, object]:
    """Construct the in-memory routing-config object before serialization."""

    routes: dict[str, object] = {}
    for i in range(_ROUTE_COUNT):
        route_key = f"/api/v{i % 4}/service-{i:04d}/resource"
        routes[route_key] = {
            "backend_pool": f"pool-{i % 32:02d}",
            "weight": (i % 100) + 1,
            "timeout_ms": 250 + (i % 7) * 125,
            "retry_policy": {
                "max_attempts": (i % 4) + 1,
                "backoff_ms": [50, 100, 200, 400][: (i % 4) + 1],
                "retry_on": ["503", "504", "connect-failure"],
            },
            "headers": {
                f"x-route-tag-{j}": f"tag-value-{i}-{j}" for j in range(6)
            },
            "shadow_targets": [
                f"shadow-pool-{(i + k) % 32:02d}" for k in range(3)
            ],
        }
    return {
        "version": "2024-11-config-snapshot",
        "default_backend": "pool-00",
        "default_headers": {f"x-default-{j}": f"d{j}" for j in range(4)},
        "routes": routes,
    }


# Serialized routing-config document. This is the "blob" the resolver receives:
# plain JSON *text* that must be parsed before any route can be looked up.
RAW_CONFIG: str = json.dumps(_build_config_object())
