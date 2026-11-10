"""Render a batch of log records into a single report document.

The reporting worker collects the log records for a time window and serializes
them into one text blob that is written to object storage and shown in the UI.
The rendered document is a header line followed by one pipe-delimited line per
record, separated by newlines, with a trailing newline.

The output is built by accumulating the rendered lines into a running ``report``
string. Each record's line is appended with ``report = report + line + "\n"``.
Because Python strings are immutable, every ``+=`` allocates a brand-new string
and copies the entire document accumulated so far before tacking the new line on
the end. For a report of N lines that means the prefix is recopied on every
iteration, so the total work grows with the square of the document length -- the
classic quadratic string-building trap. It is invisible on tiny inputs and
dominates CPU time once a window contains many thousands of records.
"""

from __future__ import annotations

from report_render.columns import format_row, header_line


def render_report(records: list[dict[str, object]]) -> str:
    """Serialize ``records`` into one pipe-delimited report document.

    Returns the header line followed by one line per record (in input order),
    newline-separated, with a trailing newline. An empty batch renders just the
    header line plus its trailing newline.
    """

    # Accumulate the document one line at a time. Each ``+=`` rebuilds the whole
    # ``report`` string built so far, so this loop is O(total_output_length^2).
    report = header_line() + "\n"
    for record in records:
        line = format_row(record)
        report = report + line + "\n"
    return report
