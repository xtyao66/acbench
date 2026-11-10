"""Tests for agent loading helpers."""

from __future__ import annotations

import unittest

from acbench.agents.loader import load_object
from acbench.agents.scripted import SubmitOnlyAIOpsAgent


class AgentLoaderTests(unittest.TestCase):
    def test_load_object_resolves_builtin_agent(self) -> None:
        obj = load_object("acbench.agents.scripted:SubmitOnlyAIOpsAgent")
        self.assertIs(obj, SubmitOnlyAIOpsAgent)


if __name__ == "__main__":
    unittest.main()
