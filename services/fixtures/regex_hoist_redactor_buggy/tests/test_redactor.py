"""Tests for the request-payload secret/PII redactor.

``test_compiles_ruleset_at_most_once`` is the performance oracle: it counts
regex-ruleset compilations deterministically (no wall-clock timing) and fails on
the per-record implementation, which rebuilds the fixed ruleset once per record.
The correctness tests pin the redacted output so a hoisted (or any other)
rewrite cannot earn credit by changing behavior, returning early, or skipping
the redaction work.
"""

from __future__ import annotations

import unittest

from payload_redactor import regexlab
from payload_redactor.redactor import redact_records


def _make_records() -> list[str]:
    return [
        "INFO login user=ada token=abc123XYZ secret here",
        "WARN visa 4111111111111111 contact ada@example.com from 10.0.0.1",
        "ERROR ssn 123-45-6789 bearer ZZ-99_aa phone (415) 555-2671",
        "plain healthcheck status=200 region=us-east no secrets",
    ]


# Expected redacted output, captured against the reference behavior. Pinning the
# full strings makes the correctness tests fail for any patch that returns early,
# skips rules, or otherwise changes what gets masked.
_EXPECTED = [
    "INFO login user=ada [REDACTED] secret here",
    "WARN visa [REDACTED] contact [REDACTED] from [REDACTED]",
    "ERROR ssn [REDACTED] [REDACTED] phone [REDACTED]",
    "plain healthcheck status=200 region=us-east no secrets",
]


class PayloadRedactorTests(unittest.TestCase):
    def setUp(self) -> None:
        # The counting compiler is process-wide; reset it before each test so
        # the compile count reflects only this redaction call.
        regexlab.COMPILER.compile_count = 0

    def test_compiles_ruleset_at_most_once(self) -> None:
        # Performance oracle: regardless of how many records arrive, the fixed
        # redaction ruleset must be assembled (parsed + compiled) at most once
        # for the whole batch. The per-record implementation compiles it N times.
        records = _make_records()
        self.assertGreater(len(records), 1)
        redact_records(records)
        self.assertLessEqual(regexlab.COMPILER.compile_count, 1)

    def test_redacts_all_secret_and_pii_kinds(self) -> None:
        # Behavioral correctness: every record is redacted exactly as expected,
        # covering tokens, credit cards, e-mails, IPs, SSNs, bearer tokens and
        # phone numbers. A fast-but-wrong patch that drops matches fails here.
        result = redact_records(_make_records())
        self.assertEqual(result, _EXPECTED)

    def test_preserves_order_count_and_clean_records(self) -> None:
        # Edge cases: output preserves input order and count, a record with no
        # secrets passes through verbatim, and multiple secrets in one record are
        # all masked (order must be stable).
        records = _make_records()
        result = redact_records(records)
        self.assertEqual(len(result), len(records))
        # Clean record is unchanged.
        self.assertEqual(result[3], records[3])
        # Record with three distinct secrets has all three masked.
        self.assertEqual(result[1].count("[REDACTED]"), 3)
        # Order is stable: first record stays first.
        self.assertTrue(result[0].startswith("INFO login user=ada"))

    def test_empty_batch_and_empty_record(self) -> None:
        # Edge cases: an empty batch yields an empty list (and compiles nothing
        # extra in the hoisted form), and an empty record round-trips to "".
        self.assertEqual(redact_records([]), [])
        self.assertEqual(redact_records(["", "clean line"]), ["", "clean line"])


if __name__ == "__main__":
    unittest.main()
