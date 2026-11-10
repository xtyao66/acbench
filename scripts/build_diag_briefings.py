#!/usr/bin/env python3
"""Build per-scenario authoring briefings for diagnosis re-authoring.

Each briefing contains ONLY pre-fix, observable material so a diagnosis can be
authored without ever seeing the fix. Deliberately EXCLUDED: ops_fault.repair_keywords
(they transcribe the fix) and of course the fix diff. Output: one JSON per scenario
under the briefings dir. The downstream authoring agents read ONLY these files.

Usage: python3 scripts/build_diag_briefings.py [out_dir]
       (default out_dir: /tmp/acbench_diag_briefings)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFESTS = ["manifests/combined_all.json", "manifests/real_prs.json"]


def briefing(sc: dict) -> dict:
    vc = sc.get("visible_context") or {}
    of = sc.get("ops_fault") or {}
    cf = sc.get("code_fault") or {}
    task = sc.get("task") or {}
    build = sc.get("build") or {}
    return {
        "scenario_id": sc["scenario_id"],
        "title": sc.get("title", ""),
        "mode": sc.get("mode", ""),
        "language": build.get("language", "python"),
        "task_summary": task.get("summary", ""),
        "task_instructions": task.get("instructions", ""),
        "issue_text": vc.get("issue_text", ""),
        "error_logs": vc.get("error_logs", []),
        "reproduction_steps": vc.get("reproduction_steps", []),
        "relevant_files": vc.get("relevant_files", []),
        "notes": vc.get("notes", ""),
        # symptom signal (observable from the failing test / incident)
        "symptom_keywords": of.get("detection_keywords", []),
        # root-cause material (the curated true root cause + localization). The
        # author must ABSTRACT these into natural language and must NOT copy any
        # code identifier / quoted literal from them (the leakage gate enforces).
        "root_cause_material": list(of.get("localization_keywords", []))
        + [s for s in [cf.get("description", ""), of.get("description", "")] if s],
        "target_files": cf.get("target_files", []),
        # NOTE: ops_fault.repair_keywords and the fix diff are intentionally absent.
    }


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/acbench_diag_briefings")
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for man in MANIFESTS:
        data = json.loads((REPO / man).read_text(encoding="utf-8"))
        for e in data["scenarios"]:
            sc = json.loads((REPO / e["scenario"]).read_text(encoding="utf-8"))
            b = briefing(sc)
            (out / f"{b['scenario_id']}.json").write_text(
                json.dumps(b, indent=2), encoding="utf-8")
            n += 1
    print(f"wrote {n} briefings to {out}")
    # The repair_keywords FIELD (the fix recipe) and the fix diff are excluded by
    # construction. We do NOT scrub generic words that happen to also appear as a
    # repair keyword (e.g. "threshold", "cleanup") -- those occur legitimately in
    # the observable issue text / localization material and removing them would
    # make the briefing incoherent. The hard guarantee that no FIX CONSTRUCT
    # reaches the authored diagnosis is the leakage gate (check_diagnosis_leakage.py),
    # which runs against the actual fix diff, not the keyword vocabulary.
    print("OK: repair_keywords field and fix diff excluded by construction")
    return 0


if __name__ == "__main__":
    sys.exit(main())
