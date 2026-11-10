"""Row-formatting helpers for the report renderer.

These functions turn a single record (a ``dict`` of column name -> value) into
the pipe-delimited text line that appears in the rendered report. They are pure
and cheap per call: the cost of rendering a whole report comes from how the
serializer *accumulates* these lines, not from formatting any one of them.
"""

from __future__ import annotations

# Fixed column order for the rendered report. Records may carry extra keys; only
# these columns are emitted, always in this order, so the output is stable.
COLUMNS: tuple[str, ...] = ("ts", "level", "service", "message")


def header_line() -> str:
    """Return the report header row (the column names, pipe-delimited)."""

    return "| " + " | ".join(COLUMNS) + " |"


def format_row(record: dict[str, object]) -> str:
    """Render one record as a pipe-delimited line over the fixed columns.

    Missing columns render as an empty cell; extra keys on the record are
    ignored so the column layout stays fixed regardless of the input shape.
    """

    cells = [str(record.get(col, "")) for col in COLUMNS]
    return "| " + " | ".join(cells) + " |"
