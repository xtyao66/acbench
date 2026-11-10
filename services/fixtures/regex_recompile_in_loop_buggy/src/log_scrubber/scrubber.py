"""Log-line secret scrubber.

The scrubber redacts API tokens out of a batch of inbound log lines before they
are shipped to the central log sink. Each line is matched against a single,
fixed redaction pattern and any token value is replaced with a ``[REDACTED]``
marker while the key (``token`` / ``api_key`` / ``secret``) is preserved.
"""

from __future__ import annotations

from log_scrubber.regexlab import compile_pattern

# Matches ``token=<value>`` / ``api_key=<value>`` / ``secret=<value>`` secrets in
# a log line, capturing the key so the redacted output keeps it. The pattern is
# constant for the whole batch — it never depends on the line.
SECRET_PATTERN = r"(token|api_key|secret)=[A-Za-z0-9_\-]+"

# Keep the matched key, replace the value with a fixed marker.
REDACTION = r"\1=[REDACTED]"


def scrub_lines(lines: list[str]) -> list[str]:
    """Redact secrets from every log line, preserving input order.

    For each line we substitute any matched secret with a redaction marker that
    keeps the key but masks the value. Lines without a secret pass through
    unchanged.
    """

    scrubbed: list[str] = []
    for line in lines:
        # Re-compiling the fixed redaction pattern on every line: this loop
        # invokes the regex compiler N times for a batch of N lines even though
        # the pattern never changes.
        pattern = compile_pattern(SECRET_PATTERN)
        scrubbed.append(pattern.sub(REDACTION, line))
    return scrubbed
