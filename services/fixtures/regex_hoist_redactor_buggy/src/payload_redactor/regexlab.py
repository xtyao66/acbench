"""In-repo regex-ruleset compiler facade that does genuine compile work.

This stands in for the layer an application uses to turn a redaction *ruleset*
(a list of pattern strings loaded from runtime config) into a list of compiled
matchers. Two things matter for the performance scenario:

* The compile is **real work**: every call genuinely parses and compiles every
  rule with the standard-library engine. Because a ruleset is assembled fresh
  from config (the pattern strings are produced at call time), the work is not
  served from the module-level pattern cache -- assembling a fresh compiled
  matcher costs real CPU every time it is invoked.
* The compile is **counted**: ``COMPILER.compile_count`` records how many times
  a ruleset was assembled, so a regression test can assert the hot path builds
  the matcher at most once per batch -- deterministically, with no timing.

The returned matchers are ordinary :class:`re.Pattern` objects, so matching
behavior is identical no matter where compilation happens; only the *cost* of
recompiling per record (vs. once per batch) differs.
"""

from __future__ import annotations

import re


class RulesetCompiler:
    """A redaction-ruleset compiler facade that counts each ruleset it builds."""

    def __init__(self) -> None:
        # Number of times a ruleset was assembled into compiled matchers.
        self.compile_count = 0

    def compile_ruleset(self, rules: list[str]) -> list[re.Pattern[str]]:
        """Compile every rule string into a matcher (one ruleset assembly).

        The pattern cache is purged first so this performs the full parse +
        compile for every rule, the way building a matcher from freshly
        assembled runtime config does. This is the genuine CPU cost the
        performance scenario is about.
        """

        self.compile_count += 1
        compiled: list[re.Pattern[str]] = []
        for rule in rules:
            # Force a real compile (cache-miss) -- a ruleset built from config
            # is not a stable, pre-cached literal.
            re.purge()
            compiled.append(re.compile(rule))
        return compiled


# Process-wide compiler so callers and the regression test observe the same
# ``compile_count``.
COMPILER = RulesetCompiler()


def compile_ruleset(rules: list[str]) -> list[re.Pattern[str]]:
    """Compile a redaction ruleset through the shared counting compiler."""

    return COMPILER.compile_ruleset(rules)
