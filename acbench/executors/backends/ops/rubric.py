"""Shared rubric logic for grading ops-incident assessments.

The ops oracle grades each incident stage (detection / localization /
remediation) on the *discriminative* keywords an agent must actually produce —
keywords that are NOT already present in the visible incident prompt — using
recall above a threshold.

Two properties make this resistant to gaming:

1. **The agent's self-reported boolean is never used.** A graded answer must not
   be scored on the gradee's own claim that it succeeded.
2. **Keywords echoed from the prompt earn no credit.** Any expected keyword that
   already appears in the visible incident evidence is treated as "leaked" and
   excluded from the credited (discriminative) set, so an agent that simply
   repeats the prompt cannot score.

When every expected keyword for a stage is leaked (no discriminative signal is
possible from the authored data), the stage is flagged ``all_keywords_leaked``
and is not gradeable: it earns no credit and does not count as passed, so the
weakness is visible rather than silently rewarded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

DEFAULT_PASS_THRESHOLD = 0.5

# Which assessment sections each stage is allowed to match against.
STAGE_SECTIONS: dict[str, tuple[str, ...]] = {
    "detection": ("summary", "root_cause", "evidence"),
    "localization": ("root_cause", "summary", "evidence"),
    "remediation": ("remediation", "root_cause", "summary", "evidence"),
}

# Map a success-criteria stage to its keyword attribute on the ops problem/fault.
STAGE_KEYWORD_ATTR: dict[str, str] = {
    "detection": "detection_keywords",
    "localization": "localization_keywords",
    "remediation": "repair_keywords",
}


def _norm(value: Any) -> str:
    return str(value).lower()


def joined_sections(assessment: Mapping[str, Any], sections: Sequence[str]) -> str:
    """Concatenate the named assessment sections into one lowercase haystack."""

    parts: list[str] = []
    for section in sections:
        value = assessment.get(section, "")
        if isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return " ".join(parts).lower()


def find_keywords(haystack_lower: str, keywords: Sequence[str]) -> list[str]:
    """Return the keywords that appear (case-insensitively) in the haystack."""

    return [keyword for keyword in keywords if _norm(keyword) in haystack_lower]


def prompt_text_for_problem(problem: Any) -> str:
    """Build the visible-prompt text an ops agent is shown, for leakage checks.

    Mirrors the fields surfaced by the ops agent prompt builder (task framing +
    incident evidence). The problem/application/service/deployment identifiers
    are included too: the agent prompt shows them, so a keyword equal to the
    service name is echoable and must not count as discriminative.
    """

    parts: list[str] = [
        getattr(problem, "problem_id", ""),
        getattr(problem, "application", ""),
        getattr(problem, "service", ""),
        getattr(problem, "deployment", ""),
        getattr(problem, "task_summary", ""),
        getattr(problem, "task_instructions", ""),
        getattr(problem, "acceptance_notes", ""),
        getattr(problem, "issue_text", ""),
        getattr(problem, "visible_notes", ""),
    ]
    for attr in ("error_logs", "reproduction_steps", "relevant_files"):
        parts.extend(str(item) for item in getattr(problem, attr, []) or [])
    return " ".join(str(part) for part in parts if part)


@dataclass(slots=True)
class StageRubric:
    """Grading outcome for one incident stage."""

    stage: str
    expected: list[str] = field(default_factory=list)
    leaked: list[str] = field(default_factory=list)
    discriminative: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    matched_discriminative: list[str] = field(default_factory=list)
    recall: float = 1.0
    threshold: float = DEFAULT_PASS_THRESHOLD
    graded_on: str = "no_keywords"
    passed: bool = True
    gradeable: bool = True

    @property
    def all_keywords_leaked(self) -> bool:
        return self.graded_on == "all_keywords_leaked"

    @property
    def has_discriminative_signal(self) -> bool:
        return bool(self.discriminative)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "recall": round(float(self.recall), 6),
            "passed": self.passed,
            "gradeable": self.gradeable,
            "threshold": self.threshold,
            "graded_on": self.graded_on,
            "all_keywords_leaked": self.all_keywords_leaked,
            "expected_keywords": list(self.expected),
            "leaked_keywords": list(self.leaked),
            "discriminative_keywords": list(self.discriminative),
            "matched_keywords": list(self.matched),
            "matched_discriminative_keywords": list(self.matched_discriminative),
        }


def evaluate_stage(
    stage: str,
    assessment: Mapping[str, Any],
    keywords: Sequence[str],
    prompt_text: str,
    *,
    threshold: float = DEFAULT_PASS_THRESHOLD,
) -> StageRubric:
    """Grade one incident stage with leakage-aware, self-report-free recall."""

    expected = [keyword for keyword in keywords if str(keyword).strip()]
    sections = STAGE_SECTIONS.get(stage, ("summary", "root_cause", "evidence", "remediation"))
    answer_text = joined_sections(assessment, sections)
    prompt_lower = _norm(prompt_text)

    if not expected:
        # Nothing to grade for this stage: treat as satisfied but flag no signal.
        return StageRubric(stage=stage, recall=1.0, graded_on="no_keywords", passed=True, threshold=threshold)

    leaked = find_keywords(prompt_lower, expected)
    leaked_lower = {_norm(keyword) for keyword in leaked}
    discriminative = [keyword for keyword in expected if _norm(keyword) not in leaked_lower]

    matched = find_keywords(answer_text, expected)
    matched_lower = {_norm(keyword) for keyword in matched}
    matched_discriminative = [keyword for keyword in discriminative if _norm(keyword) in matched_lower]

    if discriminative:
        recall = len(matched_discriminative) / len(discriminative)
        graded_on = "discriminative"
        gradeable = True
        passed = recall >= threshold
    else:
        # Every expected keyword is echoed in the visible prompt, so this stage
        # carries NO discriminative signal: a prompt-echo answer would match them
        # all without any real diagnosis. The stage is therefore not gradeable —
        # it earns no credit and is EXCLUDED from the ops score (see scoring.py),
        # and is flagged so the scenario author adds a non-leaked keyword.
        recall = len(matched) / len(expected)  # retained for telemetry only
        graded_on = "all_keywords_leaked"
        gradeable = False
        passed = False

    return StageRubric(
        stage=stage,
        expected=expected,
        leaked=leaked,
        discriminative=discriminative,
        matched=matched,
        matched_discriminative=matched_discriminative,
        recall=recall,
        threshold=threshold,
        graded_on=graded_on,
        passed=passed,
        gradeable=gradeable,
    )


def evaluate_problem(
    problem: Any,
    assessment: Mapping[str, Any],
    *,
    threshold: float = DEFAULT_PASS_THRESHOLD,
) -> dict[str, StageRubric]:
    """Grade all three stages for one ops problem and assessment."""

    prompt_text = prompt_text_for_problem(problem)
    return {
        "detection": evaluate_stage(
            "detection",
            assessment,
            getattr(problem, "detection_keywords", []),
            prompt_text,
            threshold=threshold,
        ),
        "localization": evaluate_stage(
            "localization",
            assessment,
            getattr(problem, "localization_keywords", []),
            prompt_text,
            threshold=threshold,
        ),
        "remediation": evaluate_stage(
            "remediation",
            assessment,
            getattr(problem, "repair_keywords", []),
            prompt_text,
            threshold=threshold,
        ),
    }
