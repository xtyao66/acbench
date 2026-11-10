#!/usr/bin/env python3
"""Materialize the real incident->fix PR repositories into a bug-present base state.

For every scenario in the real-PR manifest this:
  1. clones the upstream repo once (blob-filtered) into a shared cache,
  2. checks out the PR's BASE commit (the buggy state),
  3. copies the worktree -- INCLUDING .git -- into ``service.repository_path``,
  4. applies the PR's *test* patch, introducing the FAIL_TO_PASS regression test.

The result is exactly the state the ACBench code executor expects as a local
``repository_path``: the bug is present and the regression test fails, so an
agent (or the gold fix) is graded by whether it turns FAIL_TO_PASS green.

.git is STRIPPED after the test patch is applied, so ``LocalCodeExecutor``
applies agent patches via the lenient subsequence-matcher
(``apply_patch_without_git``) -- exactly like the synthetic fixtures, which are
plain dirs.  Strict ``git apply`` rejects model diffs on any line-number drift;
the lenient matcher tolerates it (this is what makes real-world apply rates
non-zero).  The test patch is applied to the working tree while .git is still
present (reliable for the exact PR diff); ``prepare_workspace`` then copies the
whole tree per run.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = os.environ.get("ACBENCH_MANIFEST", "manifests/real_prs.json")
REALROOT = Path(os.environ.get("ACBENCH_REALROOT", "/volt/realrepos"))
CACHE = REALROOT / "_cache"


def _run(cmd, cwd=None, check=True, shell=False):
    r = subprocess.run(
        cmd, cwd=cwd, shell=shell, text=True, capture_output=True
    )
    if check and r.returncode != 0:
        raise RuntimeError(
            f"command failed ({r.returncode}): {cmd}\n{(r.stderr or r.stdout)[-800:]}"
        )
    return r


def _cache_for(url: str) -> Path:
    h = hashlib.sha1(url.encode()).hexdigest()[:12]
    dst = CACHE / h
    if not (dst / ".git").exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.rmtree(dst)
        print(f"  cloning {url} -> {dst.name}", flush=True)
        _run(["git", "clone", "--filter=blob:none", "-q", url, str(dst)])
    return dst


def materialize_one(
    scenario_rel: str,
    force: bool = False,
    patch_suffix: str = "test",
    require_patch: bool = True,
) -> Path:
    """Materialize one scenario's base-state repo; returns the repository_path.

    ``patch_suffix`` selects the patch applied at base (while .git is present):
    "test" for correctness scenarios (introduces FAIL_TO_PASS), "bench" for
    measured-perf scenarios that ADD a benchmark. When ``require_patch`` is False
    and the patch file is absent (e.g. a perf PR whose benchmark pre-existed),
    the repo is materialized at base with no extra patch.
    """
    d = json.loads((ROOT / scenario_rel).read_text(encoding="utf-8"))
    sid = d["scenario_id"]
    url = d["source"]["repo_url"]
    base = d["source"]["base_commit"]
    dst = Path(d["service"]["repository_path"])
    patch = ROOT / "patches" / f"{sid}_{patch_suffix}.diff"
    if not patch.exists():
        if require_patch:
            raise FileNotFoundError(f"{sid}: missing {patch_suffix} patch {patch}")
        patch = None

    marker = dst / ".acbench_materialized"
    if dst.exists() and marker.exists() and not force:
        return dst
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    cache = _cache_for(url)
    _run(["git", "checkout", "-q", "--force", base], cwd=cache)
    _run(["git", "clean", "-fdq"], cwd=cache)
    # Copy the worktree INCLUDING .git (tar pipe preserves perms/symlinks).
    _run(f"tar -C {cache} -cf - . | tar -C {dst} -xf -", shell=True)
    # Apply the base patch (test or bench) into the working tree while .git is
    # still present so git apply is reliable for this exact PR diff.
    if patch is not None:
        r = _run(["git", "apply", "--whitespace=nowarn", str(patch)], cwd=dst, check=False)
        if r.returncode != 0:
            r2 = _run(["patch", "-p1", "-i", str(patch)], cwd=dst, check=False)
            if r2.returncode != 0:
                raise RuntimeError(
                    f"{sid}: {patch_suffix} patch did not apply:\n"
                    f"git: {r.stderr[-400:]}\npatch: {r2.stderr[-400:]}"
                )
    # Strip .git so the executor applies AGENT patches via the lenient
    # subsequence-matcher (apply_patch_without_git) -- identical to the synthetic
    # fixtures (which are plain dirs). Strict ``git apply`` rejects LLM diffs on
    # any line-number drift; the lenient matcher tolerates it. This is the single
    # most important fix for non-zero real-world apply rates.
    shutil.rmtree(dst / ".git", ignore_errors=True)
    marker.write_text(f"{sid}\n{base}\n", encoding="utf-8")
    print(f"  materialized {sid} @ {base[:12]} -> {dst}", flush=True)
    return dst


def main() -> int:
    man = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    scns = [e["scenario"] for e in man["scenarios"]]
    print(f"materializing {len(scns)} real-PR repos into {REALROOT} ...", flush=True)
    failures = []
    for s in scns:
        try:
            materialize_one(s)
        except Exception as exc:  # noqa: BLE001
            failures.append((s, str(exc)))
            print(f"  FAILED {s}: {exc}", flush=True)
    if failures:
        print(f"\n{len(failures)} materialization failures.", flush=True)
        return 1
    print("all real-PR repos materialized.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
