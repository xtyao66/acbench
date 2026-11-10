# report-render-quadratic

Local ACBench measured-performance fixture for the `string_concat_quadratic`
archetype.

The report serializer in `src/report_render/serializer.py` turns a batch of log
records into a single pipe-delimited text document (a header line plus one line
per record). It builds the document by accumulating each rendered line into a
running string with `report = report + line + "\n"`.

Because Python strings are immutable, every `+=` allocates a fresh string and
copies the **entire document accumulated so far** before appending the new line.
For a report of `N` lines the prefix is recopied on every iteration, so the
total work grows with the **square of the document length**. The cost is
invisible on tiny inputs and dominates CPU time once a window holds many
thousands of records.

`bench.py` drives `render_report` over a window of `N = 26000` synthetic records
(~2.3 MB of output) and prints one JSON line `{"elapsed_s", "n", "chars"}`. On
the quadratic baseline this takes ~0.9 s; the per-record line formatting in
`src/report_render/columns.py` is pure and cheap, so essentially all of that
time is the repeated prefix-copying in the accumulation loop.

The fix is to collect the rendered lines into a list and join them once with
`"".join(parts)` (or write them to an `io.StringIO`), turning the O(N^2)
string-building into O(N) — **no behavioral change** to the rendered document,
only to the algorithmic cost of building it. The behavioral tests in
`tests/test_serializer.py` pin the exact output byte-for-byte (header, row
order, duplicate retention, unknown-key handling, blank cells, line count) so a
fast-but-wrong rewrite earns no credit.
