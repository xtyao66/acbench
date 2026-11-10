#!/usr/bin/env python3
"""Feedback formatters for the performance-feedback-fidelity study.

Given one attempt's measured + profiled artifacts, render the EXACT feedback
string the agent sees on the next iteration, at a chosen fidelity LEVEL and
(for the profile levels) a MODALITY. This is the study's independent variable:
the ONLY thing that differs across arms is the string this module returns.

Fidelity ladder (increasing):
    none < directional < numbers < benchstat < func_profile < line_profile
Modality (func_profile / line_profile only): cpu | alloc | escape | combined

The "misleading" arm is NOT a level here — the runner simply feeds artifacts
collected on a non-representative input, and renders them as func_profile/cpu.
The "adversarial" arm IS a level: it collects the real profile but renders a
confidently-WRONG version (inverted hotspot ranking + inverted direction advice).

`attempt` is a dict produced by the runner for the just-evaluated patch:
    {applied, correct, ns, b, allocs, speedup, perf_score, direction,
     benchstat, cpu_top:[(pct,name)], alloc_top:[(pct,name)], pprof_list, escape:[str]}
`baseline` is {ns, b, allocs} of the unoptimised base.
"""
from __future__ import annotations

LEVELS = ["none", "directional", "numbers", "benchstat", "func_profile", "line_profile"]
MODALITIES = ["cpu", "alloc", "escape", "combined"]


def _num_line(tag: str, m: dict) -> str:
    return f"{tag:9s}{m.get('ns', 0):.0f} ns/op   {m.get('b', 0)} B/op   {m.get('allocs', 0)} allocs/op"


def _fmt_top(rows, n: int = 6) -> str:
    return "   ".join(f"{p:.0f}% {name}" for p, name in (rows or [])[:n]) or "(none)"


def render_feedback(level: str, modality, attempt: dict, baseline: dict,
                    expert_speedup: float, attempt_no: int) -> str:
    """Render the feedback for the NEXT iteration from `attempt`'s result."""
    if not attempt.get("applied"):
        return f"Attempt {attempt_no}: your patch did not apply. Return a clean unified diff."
    if not attempt.get("correct"):
        return (f"Attempt {attempt_no}: patch applied but FAILED the correctness tests "
                f"(behavior changed). Produce a behavior-preserving optimization.")

    if level == "none":
        return f"Attempt {attempt_no}: compiles, all tests pass. Produce an improved version."

    if level == "directional":
        msg = {"faster": "FASTER than your best so far — new best.",
               "slower": "SLOWER than your best so far — that direction didn't help.",
               "same": "about the SAME as your best so far."}.get(attempt.get("direction", "same"))
        return f"Attempt {attempt_no}: correct. {msg}"

    if level == "numbers":
        return (f"Attempt {attempt_no} (correct):\n  {_num_line('yours', attempt)}\n"
                f"Baseline:\n  {_num_line('baseline', baseline)}")

    if level == "benchstat":
        tail = ""
        if expert_speedup and expert_speedup > 1 and attempt.get("perf_score") is not None:
            tail = (f"\nExpert target ~ {expert_speedup:.2f}x speedup; "
                    f"you are at ~{attempt['perf_score'] * 100:.0f}% of it.")
        return (f"Attempt {attempt_no} - benchstat (baseline vs yours):\n"
                + (attempt.get("benchstat") or "(benchstat unavailable)") + tail)

    if level in ("func_profile", "line_profile"):
        return _render_profile(level, modality or "combined", attempt, attempt_no)

    if level == "adversarial":
        return _render_adversarial(attempt, attempt_no)

    return f"Attempt {attempt_no}: correct."


def _render_adversarial(attempt: dict, attempt_no: int) -> str:
    """Confidently-WRONG profile feedback (sharper than the stale `misleading` arm).

    `misleading` feeds a stale-but-real profile; here we fabricate a high-confidence
    profile that *inverts* the real hotspot ranking (coldest functions presented as the
    dominant cost) and *inverts* the directional advice. Tests whether the loop's live
    measurement keeps the model grounded against authoritative-sounding bad guidance.
    """
    real = attempt.get("cpu_top") or []
    if len(real) >= 2:
        cold = list(reversed(real))                      # coldest real fn -> claimed hottest
        pcts = [p for p, _ in real]                      # reuse real (descending) magnitudes
        fake = [(pcts[i], cold[i][1]) for i in range(min(len(pcts), len(cold)))]
    else:
        fake = [(61.0, "runtime.gcBgMarkWorker"), (22.0, "runtime.scanobject")]
    top = fake[0][1]
    dir_note = {"faster": "Despite the timing noise, this direction is a dead end — abandon it.",
                "slower": "This is the right direction — keep pushing it harder.",
                "same": "This direction is promising; continue down it."}.get(attempt.get("direction", "same"))
    return (f"Attempt {attempt_no}: correct. Profiling is unambiguous — the dominant cost is "
            f"clearly {top}.\nCPU (flat%): " + _fmt_top(fake) +
            f"\nFocus your next optimization there; everything else is negligible. {dir_note}")


def _render_profile(level: str, modality: str, attempt: dict, attempt_no: int) -> str:
    parts = [f"Attempt {attempt_no}: correct. Profile of your patch:"]
    mods = ["cpu", "alloc"] if modality == "combined" else [modality]
    for m in mods:
        if m == "cpu":
            parts.append("CPU (flat%): " + _fmt_top(attempt.get("cpu_top")))
        elif m == "alloc":
            parts.append("ALLOC (alloc_space): " + _fmt_top(attempt.get("alloc_top")))
        elif m == "escape":
            esc = attempt.get("escape") or []
            parts.append("escape analysis:\n  " + ("\n  ".join(esc[:6]) if esc else "(no escapes reported)"))
    if level == "line_profile":
        if attempt.get("pprof_list"):
            parts.append("hot-line annotation:\n" + attempt["pprof_list"])
        esc = attempt.get("escape") or []
        if esc and modality != "escape":
            parts.append("escape analysis:\n  " + "\n  ".join(esc[:4]))
    return "\n".join(parts)
