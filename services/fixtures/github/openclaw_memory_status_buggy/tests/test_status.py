"""Tests for the localized memory status reproduction."""

from __future__ import annotations

import unittest

from openclaw_memory_status.status import (
    render_memory_status_line,
    resolve_memory_search_config,
)


class MemoryStatusResolutionTests(unittest.TestCase):
    def test_resolution_preserves_cfg_for_fallback_provider(self) -> None:
        cfg = {
            "provider": "memory-lancedb-pro",
            "fallback": "memory-lancedb-pro",
            "embedding": "text-embedding-3-small",
        }

        resolved = resolve_memory_search_config(cfg)

        self.assertEqual(
            resolved["fallback"]["embedding"],
            "text-embedding-3-small",
        )

    def test_render_omits_missing_counts_for_plugin_status(self) -> None:
        status_line = render_memory_status_line(
            {
                "plugin": "memory-lancedb-pro",
                "vector_ready": True,
                "fts_ready": True,
            }
        )

        self.assertEqual(
            status_line,
            "plugin memory-lancedb-pro · vector ready · fts ready",
        )

    def test_render_keeps_counts_when_present(self) -> None:
        status_line = render_memory_status_line(
            {
                "plugin": "memory-lancedb-pro",
                "vector_ready": True,
                "fts_ready": True,
                "files": 10,
                "chunks": 44,
            }
        )

        self.assertIn("10 files", status_line)
        self.assertIn("44 chunks", status_line)


if __name__ == "__main__":
    unittest.main()
