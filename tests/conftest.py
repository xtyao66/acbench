"""Shared pytest setup: keep test runs out of the repository's runs/ directory."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolated_runs_dir(tmp_path_factory: pytest.TempPathFactory):
    previous = os.environ.get("ACBENCH_RUNS_DIR")
    os.environ["ACBENCH_RUNS_DIR"] = str(tmp_path_factory.mktemp("runs"))
    yield
    if previous is None:
        os.environ.pop("ACBENCH_RUNS_DIR", None)
    else:
        os.environ["ACBENCH_RUNS_DIR"] = previous
