"""Tests for the log-line secret scrubber.

``test_compiles_redaction_pattern_at_most_once`` is the performance oracle: it
counts regex-compile invocations deterministically (no wall-clock timing) and
fails on the per-line implementation, which re-compiles the fixed pattern once
per line. The correctness tests pin the redacted output so the hoisted rewrite
cannot earn credit by changing behavior.
"""

from __future__ import annotations

import unittest

from log_scrubber import regexlab
from log_scrubber.scrubber import scrub_lines


def _make_lines() -> list[str]:
    return [
        "2026-06-18 INFO request ok token=abc123 path=/v1/ping",
        "2026-06-18 WARN retry api_key=ZZ-99_aa upstream=cache",
        "2026-06-18 INFO healthcheck passed status=200",
        "2026-06-18 ERROR auth failed secret=topSEKRET user=ada",
        "2026-06-18 INFO plain line with no secrets here",
    ]


class LogScrubberTests(unittest.TestCase):
    def setUp(self) -> None:
        # The counting compiler is process-wide; reset it before each test so
        # the compile count reflects only this scrub call.
        regexlab.COMPILER.compile_count = 0

    def test_compiles_redaction_pattern_at_most_once(self) -> None:
        scrub_lines(_make_lines())
        # Performance oracle: regardless of how many lines arrive, the fixed
        # redaction pattern must be compiled at most once for the whole batch.
        self.assertLessEqual(regexlab.COMPILER.compile_count, 1)

    def test_redacts_secret_values_and_preserves_keys(self) -> None:
        scrubbed = scrub_lines(_make_lines())
        self.assertEqual(
            scrubbed[0],
            "2026-06-18 INFO request ok token=[REDACTED] path=/v1/ping",
        )
        self.assertEqual(
            scrubbed[1],
            "2026-06-18 WARN retry api_key=[REDACTED] upstream=cache",
        )
        self.assertEqual(
            scrubbed[3],
            "2026-06-18 ERROR auth failed secret=[REDACTED] user=ada",
        )

    def test_passes_through_lines_without_secrets_in_order(self) -> None:
        lines = _make_lines()
        scrubbed = scrub_lines(lines)
        # Output preserves input order and count.
        self.assertEqual(len(scrubbed), len(lines))
        # Lines without a secret are returned verbatim.
        self.assertEqual(scrubbed[2], lines[2])
        self.assertEqual(scrubbed[4], lines[4])


if __name__ == "__main__":
    unittest.main()
