"""Tiny in-repo regex compiler facade that counts compiles.

This stands in for the standard-library ``re`` compiler. Every call to
``compile`` increments ``compile_count`` on the shared :data:`COMPILER` so a
regression test can assert how many times a hot path compiled a pattern,
deterministically and without any wall-clock timing.

The returned object is a normal compiled pattern (``re.Pattern``); only the act
of compiling is instrumented, so behavior of the matcher is unchanged.
"""

from __future__ import annotations

import re


class RegexCompiler:
    """A regex compiler facade that counts each compile it performs."""

    def __init__(self) -> None:
        # Number of times a pattern was compiled. Reused (already-compiled)
        # patterns do not touch this counter.
        self.compile_count = 0

    def compile(self, pattern: str, flags: int = 0) -> re.Pattern[str]:
        """Compile a pattern string (one compile)."""

        self.compile_count += 1
        return re.compile(pattern, flags)


# Process-wide compiler so callers and the regression test observe the same
# ``compile_count``.
COMPILER = RegexCompiler()


def compile_pattern(pattern: str, flags: int = 0) -> re.Pattern[str]:
    """Compile ``pattern`` through the shared counting compiler."""

    return COMPILER.compile(pattern, flags)
