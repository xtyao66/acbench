"""Request-payload secret/PII redactor.

A request-handling service receives a batch of payload records (one string per
record) and must redact secrets and PII -- API tokens, credit-card numbers,
e-mail addresses, IPs, SSNs, bearer tokens, phone numbers -- before the records
are forwarded to a downstream log/analytics sink. Every record is matched
against the same fixed redaction *ruleset*; any matched value is replaced with a
``[REDACTED]`` marker. The returned list preserves input order and record count.
"""

from __future__ import annotations

from payload_redactor.regexlab import compile_ruleset

# Fixed redaction ruleset: secrets and common PII. These pattern strings are the
# same for every record in the batch -- they never depend on the record.
REDACTION_RULES: list[str] = [
    r"(?:password|passwd|pwd|secret|api[_-]?key|token|access[_-]?key)\s*[=:]\s*[A-Za-z0-9_\-\.\/\+]{4,128}",
    r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b",
    r"[A-Za-z0-9._%+\-]+@(?:[A-Za-z0-9\-]+\.)+[A-Za-z]{2,24}",
    r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b",
    r"\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b",
    r"(?i:bearer)\s+[A-Za-z0-9\-_\.=]+",
    r"(?:\+?\d{1,3}[ \-\.]?)?\(?\d{3}\)?[ \-\.]?\d{3}[ \-\.]?\d{4}",
]

# Replacement marker substituted in place of any matched secret/PII value.
REDACTION = "[REDACTED]"


def redact_records(records: list[str]) -> list[str]:
    """Redact secrets/PII from every payload record, preserving input order.

    For each record we apply every rule in the redaction ruleset, replacing any
    match with a fixed marker. Records with nothing sensitive pass through
    unchanged.
    """

    redacted: list[str] = []
    for record in records:
        # Re-assembling (parsing + compiling) the fixed redaction ruleset on
        # every record: this rebuilds every matcher from scratch once per
        # record, so a batch of N records invokes the regex compiler N times
        # over even though the ruleset never changes. The compilation cost is
        # pure overhead that scales linearly with the batch size.
        compiled = compile_ruleset(REDACTION_RULES)
        scrubbed = record
        for matcher in compiled:
            scrubbed = matcher.sub(REDACTION, scrubbed)
        redacted.append(scrubbed)
    return redacted
