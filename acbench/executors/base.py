"""Executor interfaces for ACBench backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from acbench.models.result import ExecutorResult
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec


class BenchmarkExecutor(ABC):
    """Base executor interface for benchmark backends."""

    def __init__(self, backend_name: str):
        self.backend_name = backend_name

    @abstractmethod
    def execute(
        self,
        scenario: ScenarioSpec,
        run_dir: Path,
        run_config: RunConfig,
    ) -> ExecutorResult:
        """Execute a scenario and return a normalized executor result."""
