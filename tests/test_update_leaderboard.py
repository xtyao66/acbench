from __future__ import annotations

import json

from scripts.update_leaderboard import _extract_rows, summarize_evaluations, update_leaderboard


def _write_eval(path, results):
    path.write_text(json.dumps({"results": results}), encoding="utf-8")
    return path


def test_summarize_evaluations_groups_scores_by_mode(tmp_path):
    eval_path = _write_eval(
        tmp_path / "eval.json",
        {
            "code-a": {"mode": "code_only", "final_score": 1.0},
            "code-b": {"mode": "code_only", "final_score": 0.5},
            "ops-a": {"mode": "ops_only", "final_score": 0.75},
            "combined-a": {"mode": "combined", "final_score": 0.25},
        },
    )

    assert summarize_evaluations([eval_path]) == {
        "scenarios": 4,
        "code": 75.0,
        "ops": 75.0,
        "combined": 25.0,
    }


def test_score_scale_is_decided_once_per_file(tmp_path):
    # A 0..100 file: its 1.0 means 1%, not 100%.
    percent = _write_eval(
        tmp_path / "percent.json",
        {
            "code-a": {"mode": "code_only", "final_score": 1.0},
            "code-b": {"mode": "code_only", "final_score": 80.0},
        },
    )
    fraction = _write_eval(
        tmp_path / "fraction.json",
        {"ops-a": {"mode": "ops_only", "final_score": 0.5}},
    )

    summary = summarize_evaluations([percent, fraction])

    assert summary["code"] == 40.5
    assert summary["ops"] == 50.0


def test_unevaluated_and_non_gradeable_scores_are_null(tmp_path):
    eval_path = _write_eval(
        tmp_path / "eval.json",
        {
            "code-a": {"mode": "code_only", "final_score": 0.0},
            "ops-a": {"mode": "ops_only", "final_score": None},
        },
    )

    summary = summarize_evaluations([eval_path])

    # A genuine 0 stays 0; a mode with no gradeable scenario is not evaluated.
    assert summary["code"] == 0.0
    assert summary["ops"] is None
    assert summary["combined"] is None
    assert summary["scenarios"] == 2


def test_update_leaderboard_replaces_matching_agent(tmp_path):
    website_js = tmp_path / "main.js"
    website_js.write_text(
        """const leaderboardRows = [
  {
    agent: "Agent A",
    model: "old",
    code: 0,
    ops: 0,
    combined: 0,
    scenarios: "0"
  }
];

function noop() {}
""",
        encoding="utf-8",
    )
    eval_path = tmp_path / "eval.json"
    eval_path.write_text(
        json.dumps({"results": {"code-a": {"mode": "code_only", "final_score": 1.0}}}),
        encoding="utf-8",
    )

    row = update_leaderboard(
        website_js=website_js,
        agent="Agent A",
        model="new",
        eval_paths=[eval_path],
    )

    assert row["code"] == 100.0
    assert row["ops"] is None
    assert row["scenarios"] == "1"
    text = website_js.read_text(encoding="utf-8")
    assert '"model": "new"' in text
    assert '"ops": null' in text
    assert "function noop() {}" in text


def test_update_leaderboard_keeps_special_characters_intact(tmp_path):
    website_js = tmp_path / "main.js"
    website_js.write_text(
        'const leaderboardRows = [\n  {\n    agent: "Baseline (ops: none)",\n    model: "m",\n'
        '    code: 1, ops: 2, combined: 3, scenarios: "1"\n  }\n];\n',
        encoding="utf-8",
    )
    eval_path = _write_eval(tmp_path / "eval.json", {"c": {"mode": "code_only", "final_score": 0.5}})

    for agent, model in (
        ("Caf\u00e9 agent", "Qwen3-Coder \u2014 FP8"),
        ("Path\\nAgent", "C:\\models\\m"),
    ):
        update_leaderboard(website_js=website_js, agent=agent, model=model, eval_paths=[eval_path])

    rows = _extract_rows(website_js.read_text(encoding="utf-8"))
    assert [row["agent"] for row in rows] == ["Baseline (ops: none)", "Caf\u00e9 agent", "Path\\nAgent"]
    assert rows[1]["model"] == "Qwen3-Coder \u2014 FP8"
    assert rows[2]["model"] == "C:\\models\\m"
