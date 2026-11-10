"""Minimal circular schema reproduction."""

from __future__ import annotations

from typing import Any


def collect_leaf_fields(
    schema: dict[str, Any],
    definitions: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Collect leaf field names from a JSON schema tree."""

    definitions = definitions or schema.get("$defs", {})
    leaf_fields: list[str] = []
    for key, value in schema.get("properties", {}).items():
        if "$ref" in value:
            ref_name = value["$ref"].split("/")[-1]
            leaf_fields.extend(collect_leaf_fields(definitions[ref_name], definitions))
            continue
        if value.get("type") == "object":
            leaf_fields.extend(collect_leaf_fields(value, definitions))
            continue
        leaf_fields.append(key)
    return leaf_fields
