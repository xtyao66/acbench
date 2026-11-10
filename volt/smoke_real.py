#!/usr/bin/env python3
"""End-to-end smoke for the real-PR Go leaderboard, through the ACBench executor.

For every scenario in the real-PR manifest this materializes the bug-present
repo and grades the GOLD fix via ``LocalCodeExecutor`` (Go backend), asserting
the full SWE-bench contract holds *through the harness* (not just bash):

  * at base (test patch only) the FAIL_TO_PASS test does NOT pass  -> bug present
  * after the gold fix the FAIL_TO_PASS test passes                -> resolved

A green smoke proves the executor's workspace prep, ``git apply`` path, Go
``-json`` parsing, and F2P id matching all line up before any GPU is spent.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "EMPTY")

from acbench.models.scenario import ScenarioSpec  # noqa: E402
from acbench.models.runtime import RunConfig  # noqa: E402
from acbench.executors.local_code import LocalCodeExecutor, canonical_test_id  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "materialize_real", ROOT / "volt" / "materialize_real.py"
)
mat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mat)  # type: ignore[union-attr]

MANIFEST = os.environ.get("ACBENCH_MANIFEST", "manifests/real_prs.json")


def main() -> int:
    man = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    scns = [e["scenario"] for e in man["scenarios"]]
    ok = 0
    total = len(scns)
    print(f"SMOKE: grading gold fix for {total} real scenarios via ACBench Go executor\n", flush=True)
    for rel in scns:
        d = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        sid = d["scenario_id"]
        f2p = d["evaluation"]["fail_to_pass"]
        try:
            mat.materialize_one(rel)
        except Exception as exc:  # noqa: BLE001
            print(f"XX {sid}: materialize failed: {exc}", flush=True)
            continue
        s = ScenarioSpec.from_file(ROOT / rel)
        gold = ROOT / "patches" / f"{sid}_fix.diff"
        rd = Path(tempfile.mkdtemp(prefix=f"smoke_{sid}_"))
        try:
            cr = LocalCodeExecutor().execute(s, rd, RunConfig(code_patch_path=str(gold)))
            pre = {canonical_test_id(k): v for k, v in cr.details.get("pre_patch_status", {}).items()}
            base_fail = all(pre.get(canonical_test_id(t)) != "pass" for t in f2p)
            got = len(cr.fail_to_pass_success)
            resolved = (
                base_fail
                and got == len(f2p)
                and not cr.fail_to_pass_failure
                and bool(cr.test_success)
            )
            status = "OK" if resolved else "XX"
            if resolved:
                ok += 1
            print(
                f"{status} {sid}: base_fail={base_fail} apply={cr.details.get('apply_success')} "
                f"f2p={got}/{len(f2p)} test_success={cr.test_success} success={cr.success}",
                flush=True,
            )
            if not resolved:
                # surface a little context for diagnosis
                print(f"     pre={dict(list(pre.items())[:3])} post_fail={cr.fail_to_pass_failure}", flush=True)
        finally:
            shutil.rmtree(rd, ignore_errors=True)
    print(f"\nSMOKE RESULT: {ok}/{total} real scenarios grade correctly (base FAIL -> gold PASS).", flush=True)
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
