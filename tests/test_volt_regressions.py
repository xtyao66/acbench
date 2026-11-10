"""Regression tests for the volt/ cluster harness.

Everything here runs offline: no model server, no network, no Go toolchain.
Benchmark/pprof parsers are fed captured text, and the runners' ``main()``
loops are driven with stubbed serving, subprocess, and measurement calls.
"""

from __future__ import annotations

import csv
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VOLT = ROOT / "volt"
for _p in (str(ROOT), str(VOLT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import perf_feedback as FB  # noqa: E402
import perf_profile as PROF  # noqa: E402
import run_experiments as RE  # noqa: E402
import run_perf_loop as RPL  # noqa: E402
import run_perf_sweep as PS  # noqa: E402

OLD_EXPERIMENT_FIELDS = [
    "model", "scenario_id", "mode", "difficulty", "condition", "diag_kind",
    "hide_location", "seed", "code_score", "final_score", "resolved",
    "f2p_success", "f2p_total", "apply_success", "gold_diag_leaks_target",
    "diag_source", "modified_files", "touched_target",
]


class _Proc:
    """Stand-in for subprocess.CompletedProcess / a served-model Popen."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def poll(self):
        return 0


def _ok_run(*args, **kwargs):
    return _Proc()


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


# --------------------------------------------------------------------------- #
# Finding 1: directional feedback reference (run_perf_loop._measure_attempt)
# --------------------------------------------------------------------------- #

def _directional_attempt(monkeypatch, cand_ns: float, best_sp):
    monkeypatch.setattr(RPL.MPG, "go_correct", lambda *a, **k: True)
    monkeypatch.setattr(RPL.PROF, "bench_numbers",
                        lambda *a, **k: {"BenchmarkX-72": {"ns": cand_ns, "b": 0, "allocs": 0}})
    return RPL._measure_attempt("cand", "p", "BenchmarkX", "", {"BenchmarkX-72": 1000.0}, 2.0,
                                best_sp, "directional", None, False, None, "", ".")


def test_directional_first_attempt_is_compared_to_the_baseline(monkeypatch):
    slower = _directional_attempt(monkeypatch, 1250.0, None)    # 0.8x, nothing tracked yet
    assert slower["direction"] == "slower"
    assert "SLOWER" in FB.render_feedback("directional", None, slower, {"ns": 1000}, 2.0, 1)
    assert _directional_attempt(monkeypatch, 900.0, None)["direction"] == "faster"   # 1.11x


def test_directional_compares_against_best_sub_baseline_attempt(monkeypatch):
    assert _directional_attempt(monkeypatch, 2000.0, 0.8)["direction"] == "slower"   # 0.5x < 0.8x
    assert _directional_attempt(monkeypatch, 1000.0, 0.8)["direction"] == "faster"   # 1.0x > 0.8x


# --------------------------------------------------------------------------- #
# run_perf_loop.main() harness: one fake scenario, scripted diffs and timings
# --------------------------------------------------------------------------- #

def _diff(tag: str) -> str:
    return f"--- a/p/x.go\n+++ b/p/x.go\n@@ -1 +1 @@\n-package p\n+package p // {tag}\n"


@pytest.fixture
def perf_loop(monkeypatch, tmp_path):
    from acbench.agents.openai_code import OpenAICodePatchAgent
    from acbench.executors.backends.code import standalone

    repo = tmp_path / "repo"
    (repo / "p").mkdir(parents=True)
    (repo / "p" / "x.go").write_text("package p\n", encoding="utf-8")
    scenario = {
        "scenario_id": "perf_fake_1",
        "build": {"test_cmds": ["go test -count=1 ./p"]},
        "evaluation": {"perf": {"pkg": "p", "benchmark": "BenchmarkX", "gold_speedup": 2.0},
                       "forbidden_paths": ["p/x_test.go"]},
        "code_fault": {"target_files": ["p/x.go"]},
    }
    scenario_path = tmp_path / "perf_fake_1.scenario.json"
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [{"scenario": str(scenario_path)}]}), encoding="utf-8")

    state = {"diffs": [], "ns": [], "prompts": [], "out": tmp_path / "artifacts"}

    def complete_patch(self, prompt, **kwargs):
        state["prompts"].append(prompt)
        return state["diffs"].pop(0)

    def bench_numbers(*args, **kwargs):
        ns = state["ns"].pop(0)
        return {"BenchmarkX-72": {"ns": ns, "b": 0, "allocs": 0}} if ns else {}

    monkeypatch.setattr(OpenAICodePatchAgent, "complete_patch", complete_patch)
    monkeypatch.setattr(standalone, "apply_patch", lambda repo_path, patch_file: (True, ""))
    monkeypatch.setattr(RPL.subprocess, "run", _ok_run)                 # pip install -e
    monkeypatch.setattr(RPL.RE, "serve_vllm", lambda: _Proc())
    monkeypatch.setattr(RPL.RE, "wait_health", lambda *a, **k: None)
    monkeypatch.setattr(RPL.RE, "NNODES", 1)
    monkeypatch.setattr(RPL.RE, "SERVE_BACKEND", "vllm")
    monkeypatch.setattr(RPL.MPG.mat, "materialize_one", lambda *a, **k: str(repo))
    monkeypatch.setattr(RPL.MPG, "apply_patch", lambda *a, **k: False)  # no live gold
    monkeypatch.setattr(RPL.MPG, "go_correct", lambda *a, **k: True)
    monkeypatch.setattr(RPL.PROF, "bench_numbers", bench_numbers)
    monkeypatch.setattr(RPL.PROF, "bench_raw", lambda *a, **k: "")
    monkeypatch.setattr(RPL.PROF, "collect_profiles", lambda *a, **k: ([], [], "", ""))
    for name, value in {"MANIFEST": str(manifest), "ARTIFACTS": state["out"], "SEEDS": [0], "K": 4,
                        "DRYRUN": False, "APPLY_FB": False, "RETRY_ONLY": False,
                        "CAPTURE_PATCHES": False,
                        "ARMS": [("directional", "directional", None, False)]}.items():
        monkeypatch.setattr(RPL, name, value)
    return state


def test_perf_loop_directional_feedback_tracks_sub_baseline_attempts(perf_loop):
    perf_loop["diffs"] = [_diff("a"), _diff("b"), _diff("c"), _diff("d")]
    perf_loop["ns"] = [1000.0, 1250.0, 2000.0, 900.0, 900.0]   # base, then 0.8x, 0.5x, 1.11x, 1.11x
    RPL.main()
    prompts = perf_loop["prompts"]
    assert len(prompts) == 4
    assert "SLOWER" in prompts[1]   # 0.8x vs the baseline (was "FASTER ... new best")
    assert "SLOWER" in prompts[2]   # 0.5x vs the best attempt so far (0.8x)
    assert "FASTER" in prompts[3]   # 1.11x


def test_perf_loop_empty_diff_does_not_resurface_an_older_diff(perf_loop):
    perf_loop["diffs"] = [_diff("a"), "", _diff("c"), _diff("d")]
    perf_loop["ns"] = [1000.0, 900.0, 900.0, 900.0]            # base + the three applied attempts
    RPL.main()
    third = perf_loop["prompts"][2]
    assert "Attempt 2: your patch did not apply" in third
    assert "package p // a" not in third  # attempt 1's diff must not be shown as attempt 2's


def test_perf_loop_skips_scenario_whose_base_benchmark_yields_nothing(perf_loop):
    perf_loop["ns"] = [None]                                     # base go test -bench failed
    RPL.main()
    assert perf_loop["prompts"] == []
    _, rows = _read_csv(perf_loop["out"] / "perfloop_gpt-oss-20b.csv")
    assert rows == []


# --------------------------------------------------------------------------- #
# Finding 3: bench_numbers must not keep partial results from a failed run
# --------------------------------------------------------------------------- #

FAILED_BENCH = (
    "goos: linux\ngoarch: arm64\npkg: example.com/p\n"
    + "BenchmarkX/small-72 \t 1000000\t      1000 ns/op\t 0 B/op\t 0 allocs/op\n" * 6
    + "BenchmarkX/large-72 \t    1000\t    900000 ns/op\t 0 B/op\t 0 allocs/op\n"
    + "BenchmarkX/large-72 \t--- FAIL: BenchmarkX/large-72\n    x_test.go:40: output mismatch\n" * 5
    + "FAIL\nexit status 1\nFAIL\texample.com/p\t20.1s\n"
)


def test_bench_numbers_returns_nothing_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(PROF, "_run", lambda *a, **k: _Proc(1, FAILED_BENCH))
    cand = PROF.bench_numbers(".", "p", "BenchmarkX", "", "1s", 6)
    assert cand == {}
    base = {"BenchmarkX/small-72": 1000.0, "BenchmarkX/large-72": 1800000.0}
    assert RPL.MPG.speedup(base, {k: v["ns"] for k, v in cand.items()}) == 0.0


def test_bench_numbers_parses_successful_run(monkeypatch):
    ok = FAILED_BENCH.split("BenchmarkX/large-72 \t--- FAIL")[0] + "PASS\nok  \texample.com/p\t20.1s\n"
    monkeypatch.setattr(PROF, "_run", lambda *a, **k: _Proc(0, ok))
    nums = PROF.bench_numbers(".", "p", "BenchmarkX", "", "1s", 6)
    assert {k: v["ns"] for k, v in nums.items()} == {"BenchmarkX/small-72": 1000.0,
                                                     "BenchmarkX/large-72": 900000.0}


# --------------------------------------------------------------------------- #
# Finding 4: B/op and allocs/op are found even when MB/s or custom metrics precede them
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("line", [
    "BenchmarkSubtract/x-72   \t  10000\t    123456 ns/op\t   4096 B/op\t      12 allocs/op\n",
    "BenchmarkSubtract/x-72   \t  10000\t    123456 ns/op\t 265.42 MB/s\t   4096 B/op\t      12 allocs/op\n",
    "BenchmarkSubtract/x-72   \t  10000\t    123456 ns/op\t 265.42 MB/s\t 3.000 items/op\t"
    "   4096 B/op\t      12 allocs/op\n",
])
def test_parse_bench_reads_mem_columns(line):
    assert PROF.parse_bench(line) == {"BenchmarkSubtract/x-72": {"ns": 123456.0, "b": 4096, "allocs": 12}}


def test_parse_bench_without_benchmem_and_keeps_min():
    out = ("BenchmarkX-72 \t 100\t 2000 ns/op\t 50.00 MB/s\n"
           "BenchmarkX-72 \t 100\t 1500 ns/op\t 66.67 MB/s\n")
    assert PROF.parse_bench(out) == {"BenchmarkX-72": {"ns": 1500.0, "b": 0, "allocs": 0}}


# --------------------------------------------------------------------------- #
# Finding 5: pprof -top display labels must not leak into the -list regex
# --------------------------------------------------------------------------- #

PPROF_TOP = (
    "      flat  flat%   sum%        cum   cum%\n"
    "  100.00MB 10.00% 10.00%   100.00MB 10.00%  runtime.malg\n"
    "  512.01MB 51.00% 61.00%   512.01MB 51.00%  "
    "github.com/prometheus/prometheus/model/labels.Labels.String.func1 (inline)\n"
    "  300.00MB 30.00% 91.00%   300.00MB 30.00%  strconv.appendQuotedWith (partial-inline)\n"
)


def test_hotfunc_strips_inline_label_and_escapes_full_symbol():
    rows = PROF.parse_pprof_top(PPROF_TOP)
    fn = RPL._hotfunc(rows)
    assert "inline" not in fn
    assert re.search(fn, "github.com/prometheus/prometheus/model/labels.Labels.String.func1")
    assert not re.search(fn, "github.com/prometheus/prometheus/model/labels.Labels.Hash.func1")
    assert RPL._hotfunc(rows[2:]) == re.escape("strconv.appendQuotedWith")


def test_hotfunc_drops_generic_type_arguments():
    fn = RPL._hotfunc([(40.0, "slices.SortFunc[...] (inline)")])
    assert re.search(fn, "slices.SortFunc[go.shape.int]")


# --------------------------------------------------------------------------- #
# Finding 2: run_experiments records failed runs instead of dropping them
# --------------------------------------------------------------------------- #

def test_run_experiments_records_failed_run_as_zero_score_row(monkeypatch, tmp_path):
    from acbench.executors.local_code import LocalCodeExecutor

    scenario = ROOT / "tasks/scenarios/github/combined/openclaw__completion_process_leak_incident.scenario.json"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [{"scenario": str(scenario)}]}), encoding="utf-8")

    def fail(self, *args, **kwargs):
        raise ValueError("Model returned an invalid unified diff after retries: no hunks")

    monkeypatch.setattr(LocalCodeExecutor, "execute", fail)
    monkeypatch.setattr(RE.subprocess, "run", _ok_run)                  # pip install, rm -rf
    monkeypatch.setattr(RE, "serve", lambda: _Proc())
    monkeypatch.setattr(RE, "wait_health", lambda *a, **k: None)
    monkeypatch.setattr(RE, "NNODES", 1)
    monkeypatch.setattr(RE, "CODE_DIR", ROOT)
    monkeypatch.setattr(RE, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(RE, "MANIFEST", str(manifest))
    monkeypatch.setattr(RE, "CONDITIONS", [("E2_none_shown", False, "none")])
    monkeypatch.setattr(RE, "SEEDS", [0])
    monkeypatch.delenv("ACBENCH_RUN_TAG", raising=False)
    monkeypatch.delenv("NODE_RANK", raising=False)
    monkeypatch.delenv("JOB_COMPLETION_INDEX", raising=False)

    RE.main()

    header, rows = _read_csv(tmp_path / "artifacts" / f"experiments_{RE.MODEL_ID.split('/')[-1]}.csv")
    assert header[:len(OLD_EXPERIMENT_FIELDS)] == OLD_EXPERIMENT_FIELDS and header[-1] == "error"
    assert len(rows) == 1
    row = rows[0]
    assert (row["code_score"], row["resolved"], row["apply_success"]) == ("0.0", "False", "False")
    assert row["error"].startswith("ValueError: Model returned an invalid unified diff")


# --------------------------------------------------------------------------- #
# Finding 7: run_perf_sweep needs a usable gold reference to normalize perf_score
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("gold_applies,gold_correct,expect_rows", [
    (False, True, False),   # gold patch does not apply -> gold ~= base -> would saturate to 1.0
    (True, False, False),   # gold breaks the behavioral guards
    (True, True, True),     # usable 2x gold
])
def test_perf_sweep_requires_usable_gold(monkeypatch, tmp_path, gold_applies, gold_correct, expect_rows):
    scenario = ROOT / "tasks/scenarios/local/combined/dedupe_filter__ingestion_cpu_incident.scenario.json"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [{"scenario": str(scenario)}]}), encoding="utf-8")

    def apply_gold(repo, patch):
        if gold_applies:
            (Path(repo) / ".gold_applied").write_text("1")
        return gold_applies

    def measure(repo):
        if Path(repo).name == "cand":
            return 0.8
        return 0.5 if (Path(repo) / ".gold_applied").exists() else 1.0

    monkeypatch.setattr(PS.subprocess, "run", _ok_run)       # apt-get, pip, git apply
    monkeypatch.setattr(PS.MP, "apply_patch", apply_gold)
    monkeypatch.setattr(PS, "measure", measure)
    monkeypatch.setattr(PS, "behavioral_ok", lambda repo, p2p: gold_correct or Path(repo).name != "gold")
    monkeypatch.setattr(PS, "SMOKE", True)
    monkeypatch.setattr(PS, "CODE", ROOT)
    monkeypatch.setattr(PS, "MANIFEST", str(manifest))
    monkeypatch.setattr(PS, "ARTIFACTS", tmp_path / "artifacts")
    monkeypatch.setattr(PS, "CONDITIONS", [("E2_none_shown", False, "none")])
    monkeypatch.setattr(PS, "SEEDS", [0])

    PS.main()

    _, rows = _read_csv(tmp_path / "artifacts" / f"perfsweep_{PS.MODEL_ID.split('/')[-1]}.csv")
    if not expect_rows:
        assert rows == []
        return
    assert len(rows) == 1
    assert float(rows[0]["gold_speedup"]) == 2.0
    assert float(rows[0]["perf_score"]) == round(math.log(1.25) / math.log(2.0), 3)


# --------------------------------------------------------------------------- #
# Finding 9: serving backend, image, and parallelism agree in every runner job YAML
# --------------------------------------------------------------------------- #

def _env(text: str, key: str, default=None):
    found = re.findall(rf'\b{key}=("[^"]*"|\S+)', text)
    return found[-1].strip('"') if found else default


RUNNER_YAMLS = sorted(
    p for p in VOLT.glob("*.yaml")
    if re.search(r"run_(perf_loop|experiments|perf_real|perf_sweep)\.py", p.read_text(encoding="utf-8"))
)


@pytest.mark.parametrize("path", RUNNER_YAMLS, ids=lambda p: p.name)
def test_job_yaml_serving_config_is_consistent(path):
    text = path.read_text(encoding="utf-8")
    image = re.search(r'^image:\s*"?([^"\n]+)', text, re.M).group(1)
    backend = _env(text, "ACBENCH_SERVE_BACKEND", "vllm")
    nnodes = int(_env(text, "NNODES", "1"))
    tp = int(_env(text, "TENSOR_PARALLEL_SIZE", "4"))
    pp = int(_env(text, "PIPELINE_PARALLEL_SIZE", "1"))
    gpus = int(_env(text, "GPUS_PER_NODE", str(tp)))
    assert ("sglang" in image) == (backend == "sglang"), f"{backend} backend on image {image}"
    if backend == "vllm" and nnodes > 1:
        assert tp * pp == nnodes * gpus, f"vLLM TPxPP={tp * pp} but {nnodes}x{gpus} GPUs"
    if backend == "sglang":
        assert not _env(text, "VLLM_EXTRA_ARGS"), "VLLM_EXTRA_ARGS is ignored by the SGLang backend"
