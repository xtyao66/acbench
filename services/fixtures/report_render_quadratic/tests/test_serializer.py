"""Tests for the report serializer.

These are behavioral guards: they pin the exact rendered document so any rewrite
of the accumulation strategy (e.g. the quadratic ``+=`` loop -> an ``"".join``
of the parts) must reproduce byte-for-byte identical output. A fast-but-wrong
patch -- one that reorders rows, drops the header, skips records, mangles
columns, or returns an empty/placeholder document -- fails these checks.
"""

from __future__ import annotations

import unittest

from report_render.serializer import render_report


def _sample_records() -> list[dict[str, object]]:
    return [
        {"ts": "t0", "level": "INFO", "service": "api", "message": "started"},
        {"ts": "t1", "level": "WARN", "service": "api", "message": "slow query"},
        {"ts": "t2", "level": "ERROR", "service": "db", "message": "timeout"},
    ]


class RenderReportTests(unittest.TestCase):
    def test_renders_exact_document(self) -> None:
        # Pin the full document byte-for-byte: header, one line per record in
        # input order, newline-separated, trailing newline.
        expected = (
            "| ts | level | service | message |\n"
            "| t0 | INFO | api | started |\n"
            "| t1 | WARN | api | slow query |\n"
            "| t2 | ERROR | db | timeout |\n"
        )
        self.assertEqual(render_report(_sample_records()), expected)

    def test_empty_batch_renders_header_only(self) -> None:
        # An empty batch must still emit the header line plus its trailing
        # newline -- not an empty string, and not a missing trailing newline.
        self.assertEqual(render_report([]), "| ts | level | service | message |\n")

    def test_preserves_input_order_and_duplicates(self) -> None:
        # Rows are emitted exactly once each, in input order, and duplicate
        # records are NOT de-duplicated -- every input row appears.
        records = [
            {"ts": "a", "level": "INFO", "service": "s", "message": "m"},
            {"ts": "b", "level": "INFO", "service": "s", "message": "m"},
            {"ts": "a", "level": "INFO", "service": "s", "message": "m"},
        ]
        out = render_report(records)
        body = out.splitlines()[1:]
        self.assertEqual(
            body,
            [
                "| a | INFO | s | m |",
                "| b | INFO | s | m |",
                "| a | INFO | s | m |",
            ],
        )

    def test_unknown_keys_ignored_and_missing_cells_blank(self) -> None:
        # Extra keys on a record are dropped; columns absent from a record
        # render as an empty cell, keeping the fixed column layout.
        records = [
            {"ts": "x", "level": "INFO", "service": "api", "message": "ok",
             "trace_id": "ignored", "span": 7},
            {"ts": "y", "service": "api"},  # missing level + message
        ]
        out = render_report(records)
        self.assertEqual(
            out,
            "| ts | level | service | message |\n"
            "| x | INFO | api | ok |\n"
            "| y |  | api |  |\n",
        )

    def test_line_count_matches_records(self) -> None:
        # Exactly one line per record plus the header, so a patch that skips or
        # truncates work (returning a short or empty document) is caught.
        records = [
            {"ts": str(i), "level": "INFO", "service": "s", "message": f"m{i}"}
            for i in range(200)
        ]
        out = render_report(records)
        self.assertTrue(out.endswith("\n"))
        self.assertEqual(out.count("\n"), 201)  # 200 records + 1 header
        self.assertIn("| 199 | INFO | s | m199 |", out)


if __name__ == "__main__":
    unittest.main()
