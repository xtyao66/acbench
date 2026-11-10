"""Minimal memory status/config reproduction."""

from __future__ import annotations


def merge_config(
    cfg: dict[str, object],
    defaults: dict[str, object],
    overrides: dict[str, object],
) -> dict[str, object]:
    """Build the effective config for one status check."""

    merged = dict(defaults)
    merged.update(cfg)
    merged.update(overrides)
    return merged


def get_memory_embedding_provider(
    provider: str,
    cfg: dict[str, object] | None = None,
) -> dict[str, object]:
    """Resolve one memory embedding provider."""

    cfg = cfg or {}
    embedding = cfg.get("embedding")
    if provider == "memory-lancedb-pro" and not embedding:
        raise ValueError(
            "invalid config: embedding: must have required property 'embedding'"
        )
    return {
        "provider": provider,
        "embedding": embedding or "missing",
    }


def resolve_memory_search_config(
    cfg: dict[str, object],
    defaults: dict[str, object] | None = None,
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    """Resolve the provider chain used by status --deep."""

    defaults = defaults or {}
    overrides = overrides or {}
    merged = merge_config(cfg, defaults, overrides)
    provider = str(merged["provider"])
    fallback = str(merged.get("fallback", "none"))

    resolved: dict[str, object] = {
        "primary": get_memory_embedding_provider(provider, merged)
    }
    if fallback and fallback != "none":
        resolved["fallback"] = get_memory_embedding_provider(fallback)
    return resolved


def render_memory_status_line(memory: dict[str, object]) -> str:
    """Render one human-readable memory status line."""

    parts = [f"plugin {memory['plugin']}", "vector ready", "fts ready"]
    parts.append(f"{memory.get('files')} files")
    parts.append(f"{memory.get('chunks')} chunks")
    return " · ".join(parts)
