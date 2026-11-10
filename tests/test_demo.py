"""Tests for the local demo helper."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from acbench.orchestrator.demo import run_local_demo


class DemoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="acbench-demo-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_run_local_demo_writes_outputs(self) -> None:
        bundle = run_local_demo(self.temp_dir)
        self.assertTrue(Path(bundle["json_path"]).exists())
        self.assertTrue(Path(bundle["markdown_path"]).exists())
        # 12 gold runs; the notifier DLQ scenario is not gradeable (all keywords leaked).
        self.assertEqual(bundle["results"]["success"], 11)
