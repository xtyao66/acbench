"""Helpers for coupling an ops diagnosis to the code-repair stage.

In a ``combined`` scenario the ops diagnosis produced by the ops stage is fed
into the code stage so the repair is informed by the diagnosis (rather than the
two stages running independently). These helpers format the diagnosis for the
code agent prompt and report whether the resulting repair is consistent with the
diagnosed root cause.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def format_ops_diagnosis(diagnosis: Mapping[str, Any] | None) -> str:
    """Render an ops diagnosis as a prompt section, or "" when absent."""

    if not diagnosis:
        return ""
    lines = [
        "UPSTREAM OPS DIAGNOSIS (from the incident-analysis stage).",
        "Use this diagnosis to target the root cause; the fix should address it:",
    ]
    for key, label in (
        ("summary", "Summary"),
        ("root_cause", "Root cause"),
        ("remediation", "Suggested remediation"),
    ):
        value = str(diagnosis.get(key, "")).strip()
        if value:
            lines.append(f"- {label}: {value}")
    evidence = diagnosis.get("evidence")
    if isinstance(evidence, (list, tuple)) and evidence:
        rendered = "; ".join(str(item).strip() for item in evidence[:5] if str(item).strip())
        if rendered:
            lines.append(f"- Evidence: {rendered}")
    return "\n".join(lines)


def localization_consistent(
    diagnosis: Mapping[str, Any] | None,
    modified_paths: Sequence[str],
    localization_keywords: Sequence[str],
) -> bool | None:
    """Whether the repaired files are consistent with the diagnosed location.

    Returns True/False when a judgement is possible, or None when there is not
    enough signal (no diagnosis, no modified files, or no localization keywords).
    A repair is "consistent" when a localization keyword token appears in a
    modified file path, or a modified file's stem appears in the diagnosis text.
    """

    if not diagnosis or not modified_paths or not localization_keywords:
        return None

    paths_lower = [str(p).replace("\\", "/").lower() for p in modified_paths]
    for keyword in localization_keywords:
        for token in str(keyword).lower().replace("/", " ").replace(".", " ").split():
            if len(token) < 3:
                continue
            if any(token in path for path in paths_lower):
                return True

    diagnosis_text = " ".join(
        str(diagnosis.get(key, "")) for key in ("root_cause", "summary", "remediation")
    ).lower()
    for path in paths_lower:
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if len(stem) >= 3 and stem in diagnosis_text:
            return True
    return False
