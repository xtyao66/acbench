"""Simple built-in agents for integration testing and scaffolding."""

from __future__ import annotations


class SubmitOnlyAIOpsAgent:
    """Minimal standalone ops agent that always submits immediately."""

    def init_context(self, problem_desc: str, instructions: str, apis: dict) -> None:
        self.problem_desc = problem_desc
        self.instructions = instructions
        self.apis = apis

    async def get_action(self, input_text: str) -> str:
        return "```\nsubmit()\n```"


class DetectionYesAIOpsAgent:
    """Minimal detection-task agent that submits a valid positive detection."""

    def init_context(self, problem_desc: str, instructions: str, apis: dict) -> None:
        self.problem_desc = problem_desc
        self.instructions = instructions
        self.apis = apis

    async def get_action(self, input_text: str) -> str:
        return "```\nsubmit(\"Yes\")\n```"


class ReplayAIOpsAgent:
    """Standalone ops agent that replays a fixed list of actions."""

    def __init__(self, actions: list[str] | None = None):
        self.actions = list(actions or ["```\nsubmit()\n```"])

    def init_context(self, problem_desc: str, instructions: str, apis: dict) -> None:
        self.problem_desc = problem_desc
        self.instructions = instructions
        self.apis = apis

    async def get_action(self, input_text: str) -> str:
        if self.actions:
            return self.actions.pop(0)
        return 'submit("prototype-submit")'
