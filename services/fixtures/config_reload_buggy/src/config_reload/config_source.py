"""Tiny in-repo config source that counts file reads / parses.

This stands in for an on-disk (or remote) configuration file. Every call to
``load`` reads the raw bytes and parses them into a rules dict, and increments
``read_count`` so a regression test can assert how many times a handler re-reads
the same unchanged config, deterministically and without any wall-clock timing.
"""

from __future__ import annotations

import json


class PricingConfigSource:
    """A fake pricing-rules config file that counts each read+parse it serves."""

    def __init__(self, raw_text: str) -> None:
        # The raw, unparsed config payload, as it would sit on disk.
        self._raw_text = raw_text
        # Number of times the config has been read off the backing store and
        # parsed. Each ``load`` call counts as exactly one read+parse.
        self.read_count = 0

    def load(self) -> dict[str, float]:
        """Read and parse the pricing rules (one file read + parse)."""

        self.read_count += 1
        parsed = json.loads(self._raw_text)
        return {str(sku): float(price) for sku, price in parsed["prices"].items()}
