#!/usr/bin/env python3
"""Collect Go profiling artifacts for the perf-feedback-fidelity study.

Wraps `go test -bench`, `go tool pprof`, and `go build -gcflags=-m`, parsing
their output into the structured artifacts that perf_feedback.render_feedback
consumes. Everything is CPU-only. Each collector degrades gracefully (returns
empty/partial on failure) so a missing profile never crashes the loop.

Pure-parser functions (parse_bench, parse_pprof_top) are unit-testable without Go.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# BenchmarkX-8   1000   1234 ns/op   896 B/op   17 allocs/op
# (MB/s from b.SetBytes and b.ReportMetric columns sit between ns/op and B/op, so
#  B/op and allocs/op are searched for independently in the rest of the line.)
_BENCH = re.compile(r"^(Benchmark\S+)\s+\d+\s+([\d.]+)\s+ns/op(.*)$", re.M)
_B_OP = re.compile(r"\s(\d+)\s+B/op")
_ALLOCS_OP = re.compile(r"\s(\d+)\s+allocs/op")
# pprof -top row:  2.10s 58.00% 58.00%  2.10s 58.00%  runtime.concatstrings
_PPROF_TOP = re.compile(r"^\s*[\d.]+\w*\s+([\d.]+)%\s+[\d.]+%\s+[\d.]+\w*\s+[\d.]+%\s+(\S.*)$", re.M)


def parse_bench(stdout: str) -> dict:
    """{sub_benchmark: {ns, b, allocs}} taking min ns/op per sub-benchmark."""
    out: dict = {}
    for name, ns, rest in _BENCH.findall(stdout):
        v = float(ns)
        rec = out.get(name)
        if rec is None or v < rec["ns"]:
            b, al = _B_OP.search(rest), _ALLOCS_OP.search(rest)
            out[name] = {"ns": v, "b": int(b.group(1)) if b else 0, "allocs": int(al.group(1)) if al else 0}
    return out


def parse_pprof_top(stdout: str):
    """[(flat_pct, symbol)] from `go tool pprof -top` output."""
    return [(float(p), name.strip()) for p, name in _PPROF_TOP.findall(stdout)]


def aggregate(nums: dict) -> dict:
    """Collapse {sub: {ns,b,allocs}} to one representative dict (geomean ns, mean b/allocs)."""
    if not nums:
        return {"ns": 0.0, "b": 0, "allocs": 0}
    import math
    ns = math.exp(sum(math.log(v["ns"]) for v in nums.values()) / len(nums))
    b = round(sum(v["b"] for v in nums.values()) / len(nums))
    al = round(sum(v["allocs"] for v in nums.values()) / len(nums))
    return {"ns": ns, "b": b, "allocs": al}


def _run(cmd, cwd, timeout=900):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        class _R:
            returncode = 1
            stdout = ""
            stderr = str(exc)
        return _R()


def bench_numbers(repo, pkg, bench, race="", benchtime="1s", count=6) -> dict:
    cmd = ["go", "test", "-run", "^$", "-bench", f"^{bench}$", "-benchmem",
           "-benchtime", benchtime, "-count", str(count)]
    if race:
        cmd.append(race)
    cmd.append(f"./{pkg}")
    p = _run(repo and cmd, repo)
    # A non-zero exit means a (sub-)benchmark failed or panicked: return nothing rather
    # than the runs that happened to print (same rule as measure_perf_go.go_measure).
    if p.returncode != 0:
        return {}
    return parse_bench(p.stdout)


def bench_raw(repo, pkg, bench, race="", benchtime="1s", count=6) -> str:
    """Raw `go test -bench` text — feed to benchstat."""
    cmd = ["go", "test", "-run", "^$", "-bench", f"^{bench}$", "-benchmem",
           "-benchtime", benchtime, "-count", str(count)]
    if race:
        cmd.append(race)
    cmd.append(f"./{pkg}")
    return _run(cmd, repo).stdout


def benchstat(repo, base_txt_path, cand_txt_path) -> str:
    p = _run(["benchstat", base_txt_path, cand_txt_path], repo)
    return p.stdout if p.returncode == 0 else ""


def collect_profiles(repo, pkg, bench, race="", benchtime="1s"):
    """Run one profiled bench; return (cpu_top, alloc_top, cpu_path, mem_path)."""
    cpu = str(Path(repo) / "_acb_cpu.out")
    mem = str(Path(repo) / "_acb_mem.out")
    cmd = ["go", "test", "-run", "^$", "-bench", f"^{bench}$", "-benchtime", benchtime,
           "-cpuprofile", cpu, "-memprofile", mem]
    if race:
        cmd.append(race)
    cmd.append(f"./{pkg}")
    _run(cmd, repo)
    cpu_top = parse_pprof_top(_run(["go", "tool", "pprof", "-top", "-nodecount", "8", cpu], repo).stdout) \
        if os.path.exists(cpu) else []
    alloc_top = parse_pprof_top(_run(
        ["go", "tool", "pprof", "-top", "-nodecount", "8", "-sample_index", "alloc_space", mem], repo).stdout) \
        if os.path.exists(mem) else []
    return cpu_top, alloc_top, cpu, mem


def pprof_list(repo, prof_path, func, sample_index=None, max_lines=24) -> str:
    cmd = ["go", "tool", "pprof", f"-list={func}"]
    if sample_index:
        cmd += ["-sample_index", sample_index]
    cmd.append(prof_path)
    out = _run(cmd, repo).stdout.splitlines()
    return "\n".join(out[:max_lines])


def escape_analysis(repo, pkg, target_file, max_lines=8):
    p = _run(["go", "build", "-gcflags=-m", f"./{pkg}"], repo)
    base = os.path.basename(target_file)
    keys = ("escapes to heap", "moved to heap")
    lines = [ln.strip() for ln in (p.stdout + p.stderr).splitlines()
             if base in ln and any(k in ln for k in keys)]
    return lines[:max_lines]
