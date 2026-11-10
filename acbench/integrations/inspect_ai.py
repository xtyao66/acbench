"""Run ACBench scenarios as an inspect-ai Task.

This exposes ACBench's "incident-to-fix" scenarios as an
[inspect-ai](https://inspect.aisi.org.uk/) Task, so they can be evaluated with
inspect's model providers, logging, and viewer — while grading reuses ACBench's
real executors and scorecard (test-execution for code, the leakage-aware rubric
for ops). Scores therefore match the native ACBench runner.

The model under test (set with ``inspect eval --model ...``) generates the patch
and/or the diagnosis; ACBench grades it. Combined scenarios are genuinely
two-step: the model first diagnoses, then the diagnosis is fed into the repair
prompt (the same coupling the native runner does).

Usage::

    pip install -e ".[inspect]"
    inspect eval acbench.integrations.inspect_ai:acbench_task \\
        -T manifest=manifests/local_suite.json --model openai/gpt-4.1-mini

Requires running from the ACBench repo root (scenarios reference repo-relative
fixtures).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageUser
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import Generate, Solver, TaskState, solver

from acbench.agents.openai_code import OpenAICodePatchAgent
from acbench.agents.openai_ops import OpenAIOpsAgent
from acbench.executors.backends.ops.runtime import NativeOpsProblem
from acbench.executors.local_code import LocalCodeExecutor
from acbench.executors.local_ops import LocalOpsExecutor
from acbench.models.result import BenchmarkResult
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec
from acbench.paths import resolve_repo_path
from acbench.scoring import build_scorecard


class InspectStaticOpsAgent:
    """Ops 'agent' that returns an assessment supplied via ``ops_agent_config``.

    Lets the inspect solver generate the assessment with inspect's model while
    grading it through ACBench's real ops engine + leakage-aware rubric.
    """

    def configure(self, run_config: Any = None, **_: Any) -> None:
        section = dict(getattr(run_config, "ops_agent_config", {}) or {})
        self._assessment = dict(section.get("assessment", {}))

    def analyze(self, problem: Any, *, output_dir: Path) -> dict[str, Any]:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return {"assessment": getattr(self, "_assessment", {}), "telemetry": {}}


_OPS_AGENT_REF = "acbench.integrations.inspect_ai:InspectStaticOpsAgent"


def _load_scenario(path: str) -> ScenarioSpec:
    return ScenarioSpec.from_file(path)


def _code_prompt(scenario: ScenarioSpec, diagnosis: dict | None = None) -> str:
    run_config = RunConfig(upstream_ops_diagnosis=diagnosis)
    return OpenAICodePatchAgent()._build_prompt(scenario, run_config)


def _ops_prompt(scenario: ScenarioSpec) -> str:
    return OpenAIOpsAgent()._build_prompt(NativeOpsProblem.from_scenario(scenario))


def acbench_dataset(manifest: str) -> MemoryDataset:
    """Build an inspect dataset from an ACBench manifest."""

    manifest_path = resolve_repo_path(manifest)
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    samples: list[Sample] = []
    for entry in data["scenarios"]:
        scenario_path = resolve_repo_path(entry["scenario"])
        scenario = ScenarioSpec.from_file(scenario_path)
        samples.append(
            Sample(
                input=scenario.task.summary or scenario.title,
                id=scenario.scenario_id,
                metadata={"scenario_path": str(scenario_path), "mode": scenario.mode},
            )
        )
    return MemoryDataset(samples)


@solver
def acbench_solver() -> Solver:
    """Generate the patch and/or diagnosis for an ACBench scenario."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        scenario = _load_scenario(state.metadata["scenario_path"])
        mode = scenario.mode
        if mode == "ops_only":
            state.messages = [ChatMessageUser(content=_ops_prompt(scenario))]
            state = await generate(state)
        elif mode == "code_only":
            state.messages = [ChatMessageUser(content=_code_prompt(scenario))]
            state = await generate(state)
        else:  # combined: diagnose, then repair informed by the diagnosis
            state.messages = [ChatMessageUser(content=_ops_prompt(scenario))]
            state = await generate(state)
            assessment = OpenAIOpsAgent._extract_assessment(state.output.completion)
            state.metadata["assessment"] = assessment
            state.messages = [ChatMessageUser(content=_code_prompt(scenario, assessment))]
            state = await generate(state)
        return state

    return solve


def _grade(scenario: ScenarioSpec, state: TaskState) -> dict[str, Any]:
    mode = scenario.mode
    result = BenchmarkResult(scenario_id=scenario.scenario_id, title=scenario.title, mode=mode)
    with tempfile.TemporaryDirectory(prefix="acbench-inspect-") as tmp:
        run_dir = Path(tmp)
        assessment = state.metadata.get("assessment")
        if mode in ("ops_only", "combined"):
            if assessment is None:
                assessment = OpenAIOpsAgent._extract_assessment(state.output.completion)
            ops_dir = run_dir / "ops"
            ops_dir.mkdir(parents=True, exist_ok=True)
            ops_config = RunConfig(
                aiops_agent_ref=_OPS_AGENT_REF,
                ops_agent_config={"assessment": assessment},
            )
            result.ops_result = LocalOpsExecutor().execute(scenario, ops_dir, ops_config)
        if mode in ("code_only", "combined"):
            patch_text = OpenAICodePatchAgent._extract_patch(state.output.completion)
            patch_text = OpenAICodePatchAgent._normalize_unified_diff(patch_text)
            code_dir = run_dir / "code"
            code_dir.mkdir(parents=True, exist_ok=True)
            patch_file = code_dir / "patch.diff"
            patch_file.write_text(patch_text, encoding="utf-8")
            code_config = RunConfig(
                code_patch_path=str(patch_file),
                upstream_ops_diagnosis=assessment if mode == "combined" else None,
            )
            result.code_result = LocalCodeExecutor().execute(scenario, code_dir, code_config)
        return build_scorecard(scenario, result)


@scorer(metrics=[mean(), stderr()])
def acbench_scorer() -> Scorer:
    """Grade the model output with ACBench's real executors + scorecard."""

    async def score(state: TaskState, target: Target) -> Score:
        scenario = _load_scenario(state.metadata["scenario_path"])
        card = _grade(scenario, state)
        return Score(
            # A scenario with nothing gradeable has final_score None; it earns no credit.
            value=float(card.get("final_score") or 0.0),
            answer=(state.output.completion or "")[:200],
            metadata={
                "ops_score": card.get("ops_score"),
                "code_score": card.get("code_score"),
                "score_breakdown": card.get("score_breakdown", {}),
                "failure_reasons": card.get("failure_reasons", []),
            },
        )

    return score


@task
def acbench_task(manifest: str = "manifests/local_suite.json") -> Task:
    """An inspect Task over an ACBench manifest."""

    return Task(
        dataset=acbench_dataset(manifest),
        solver=acbench_solver(),
        scorer=acbench_scorer(),
    )
