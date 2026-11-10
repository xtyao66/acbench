"""CI gate: re-authored diagnoses must not name the construct the fix uses.

Skips cleanly when no authored diagnoses are present yet (tasks/diagnoses empty),
so it never blocks before Step 1 completes; once files exist it asserts every one
is leak-free against its fix diff. See scripts/check_diagnosis_leakage.py.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from check_diagnosis_leakage import main, scan_one, DEFAULT_MANIFESTS, DEFAULT_DIAG_DIR  # noqa: E402


class TestDiagnosisLeakage(unittest.TestCase):
    def test_no_fix_leak(self) -> None:
        diag_dir = REPO / DEFAULT_DIAG_DIR
        checked = 0
        offenders = []
        for man in DEFAULT_MANIFESTS:
            data = json.loads((REPO / man).read_text(encoding="utf-8"))
            for e in data["scenarios"]:
                sc = json.loads((REPO / e["scenario"]).read_text(encoding="utf-8"))
                dp = diag_dir / f"{sc['scenario_id']}.json"
                if not dp.exists():
                    continue
                diag = json.loads(dp.read_text(encoding="utf-8"))
                off = scan_one(sc, REPO, diag)
                n = len(off.get("idents", [])) + len(off.get("strings", [])) + len(off.get("nums", []))
                checked += 1
                if n:
                    offenders.append((sc["scenario_id"], off))
        if checked == 0:
            self.skipTest("no authored diagnoses present yet")
        self.assertEqual(offenders, [], f"diagnoses leak fix tokens: {offenders}")


class TestMissingFixDiff(unittest.TestCase):
    """A diagnosis whose fix diff cannot be found is never reported as clean."""

    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="acbench-leak-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.scenario = {"scenario_id": "sid_no_diff", "gold_patch_path": "patches/missing.diff"}
        (self.repo / "manifests").mkdir()
        (self.repo / "diags").mkdir()
        (self.repo / "s.json").write_text(json.dumps(self.scenario), encoding="utf-8")
        (self.repo / "manifests" / "m.json").write_text(
            json.dumps({"scenarios": [{"scenario": "s.json"}]}), encoding="utf-8"
        )
        (self.repo / "diags" / "sid_no_diff.json").write_text(
            json.dumps({"gold": {"summary": "set eligible_units to 42"}, "wrong": {}}),
            encoding="utf-8",
        )

    def _gate(self, *extra: str) -> int:
        argv = ["check_diagnosis_leakage.py", "--repo", str(self.repo),
                "--manifests", "manifests/m.json", "--diag-dir", "diags", *extra]
        with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
            return main()

    def test_scan_one_raises_without_fix_diff(self) -> None:
        with self.assertRaises(FileNotFoundError):
            scan_one(self.scenario, self.repo, {"gold": {"summary": "x"}})

    def test_gate_fails_without_fix_diff_even_with_allow_missing(self) -> None:
        self.assertEqual(self._gate("--allow-missing"), 1)

    def test_allow_missing_still_covers_missing_diagnosis_files(self) -> None:
        (self.repo / "diags" / "sid_no_diff.json").unlink()
        self.assertEqual(self._gate(), 1)
        self.assertEqual(self._gate("--allow-missing"), 0)


if __name__ == "__main__":
    unittest.main()
