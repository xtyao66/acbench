"""Tests for the localized schema traversal reproduction."""

from __future__ import annotations

import unittest

from openclaw_schema_validation.schema import collect_leaf_fields


ACYCLIC_SCHEMA = {
    "properties": {
        "plugin": {
            "type": "object",
            "properties": {
                "apiKey": {"type": "string"},
                "region": {"type": "string"},
            },
        }
    }
}

CIRCULAR_SCHEMA = {
    "properties": {
        "plugin": {"$ref": "#/$defs/provider"}
    },
    "$defs": {
        "provider": {
            "type": "object",
            "properties": {
                "credentials": {"$ref": "#/$defs/credentials"},
                "region": {"type": "string"},
            },
        },
        "credentials": {
            "type": "object",
            "properties": {
                "apiKey": {"type": "string"},
                "provider": {"$ref": "#/$defs/provider"},
            },
        },
    },
}


class SchemaTraversalTests(unittest.TestCase):
    def test_simple_schemas_collect_leaf_fields(self) -> None:
        self.assertEqual(
            sorted(collect_leaf_fields(ACYCLIC_SCHEMA)),
            ["apiKey", "region"],
        )

    def test_circular_refs_are_only_visited_once(self) -> None:
        self.assertEqual(
            sorted(set(collect_leaf_fields(CIRCULAR_SCHEMA))),
            ["apiKey", "region"],
        )


if __name__ == "__main__":
    unittest.main()
