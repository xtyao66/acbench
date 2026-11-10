"""Load-bearing correctness-gated performance score for the Go-PR optimization
benchmark described in the HPEC 2026 paper.

This is the *authoritative* implementation of the paper's Eq. (1):

    perf_score(r, s) = clamp(log(r) / log(gold_s), 0, 1)   if go_test passes
                     = 0                                     otherwise

It is deliberately kept separate from ``acbench/scoring.py``. That module
implements the general ACBench component-weighted SWE-bench-style scorecard
(build / test / fail_to_pass / pass_to_pass and ops detection / localization /
remediation) used by the *code-repair* and *ops* tracks. The performance track
does NOT use that scorecard: a performance candidate is graded on a live
wall-clock speedup, gated by the ``go test`` correctness oracle, and normalized
by the scenario's own live-measured gold speedup. The two metrics answer
different questions and are intentionally distinct; this file is the one the
performance results (F1/F2/F3) are computed from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    repo: str
    pr: str
    gold_speedup: float  # live-measured on GB200 under the human patch, > 1.0


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def perf_score(measured_speedup: float, gold_speedup: float, go_test_passed: bool) -> float:
    """Correctness-gated, per-scenario log-ceiling performance score in [0, 1].

    Args:
        measured_speedup: baseline_time / candidate_time, obtained by LIVE
            re-measurement of the candidate patch (never the model's self-report).
        gold_speedup: the scenario's live-measured gold speedup g_s (> 1.0).
        go_test_passed: whether the scenario's ``go test`` suite passes under
            the patched tree. A candidate that changes behavior scores 0 even
            if faster.

    Returns:
        0.0 if the correctness oracle fails or the candidate is no faster than
        baseline; otherwise clamp(log r / log g_s, 0, 1).
    """
    if not go_test_passed:
        return 0.0
    if gold_speedup <= 1.0:
        raise ValueError(f"gold_speedup must exceed 1.0, got {gold_speedup}")
    if measured_speedup <= 1.0:
        # correct-but-not-faster (incl. timing noise dipping below baseline)
        return 0.0
    return clamp(math.log(measured_speedup) / math.log(gold_speedup), 0.0, 1.0)


def cell_score_best_of_k(candidates: list[tuple[float, bool]], gold_speedup: float) -> float:
    """Best-of-K per-cell statistic: max perf_score over the K candidates.

    Each candidate is (measured_speedup, go_test_passed). This is an
    upward-biased estimator of central tendency (documented as a limitation in
    the paper); at ~1 seed its cell-level variance is not estimable.
    """
    if not candidates:
        return 0.0
    return max(perf_score(r, gold_speedup, ok) for (r, ok) in candidates)


if __name__ == "__main__":
    # Sanity checks matching the paper's stated behavior.
    assert perf_score(2.0, 2.0, True) == 1.0  # matches gold -> caps at 1
    assert perf_score(1.0, 2.0, True) == 0.0  # no speedup -> 0
    assert perf_score(4.0, 2.0, True) == 1.0  # exceeds gold -> clamped to 1
    assert perf_score(2.0, 2.0, False) == 0.0  # broken -> 0 regardless of speed
    # low-gold scenario amplifies a small win (documented weighting cost):
    s = perf_score(1.10, 1.17, True)
    assert 0.60 < s < 0.62, s
    print("perf_score reference OK; low-gold(1.10x on 1.17x gold)=%.3f" % s)
