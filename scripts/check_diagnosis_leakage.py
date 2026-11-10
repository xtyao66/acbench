#!/usr/bin/env python3
"""Leakage CI gate for the diagnosis-quality study.

A re-authored diagnosis (gold / wrong) must describe the bug's symptom and
root cause at the *function/module* level WITHOUT naming the specific construct
the fix introduces or removes. This gate enforces that property mechanically:
for each scenario it extracts the "fix tokens" from the CHANGED (+/-) lines of
the fix diff and asserts that none of them appear in the diagnosis text.

What counts as a fix token (i.e. "naming the construct the fix uses"):
  * code identifiers that are unambiguously code, not English:
      camelCase (valueList), snake_case (eligible_units), ALLCAPS consts
      (_EMPTY_), mixed alnum (sha256), or very long tokens.
  * quoted string literals introduced/removed by the fix ("running").
  * numeric literals NEWLY added by the fix (present in + lines, absent in -).
Function/module names that appear only in the @@ hunk header (context, not the
edit itself) are NOT flagged -- gold is allowed to localize to a function.

Diff resolution per scenario id: scenario.gold_patch_path, else
patches/<sid>_fix.diff, else patches/<defect_id>_fix.diff, else
patches/github/<sid>.diff.

Usage:
  python3 scripts/check_diagnosis_leakage.py                 # gate (exit 1 on leak/missing)
  python3 scripts/check_diagnosis_leakage.py --report        # list, never fail
  python3 scripts/check_diagnosis_leakage.py --json          # machine-readable
  python3 scripts/check_diagnosis_leakage.py --allow-missing # don't fail on missing diag files
Importable: scan_one(scenario_dict, repo_root, diag) -> {idents, strings, nums}
            (raises FileNotFoundError when no fix diff resolves)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MANIFESTS = ["manifests/combined_all.json", "manifests/real_prs.json"]
DEFAULT_DIAG_DIR = "tasks/diagnoses"

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_STRLIT = re.compile(r"\"([^\"\\\n]{3,})\"|'([^'\\\n]{3,})'|`([^`\\\n]{3,})`")
_NUM = re.compile(r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?(?![A-Za-z0-9_])")
_CAMEL = re.compile(r"[a-z][A-Z]")
_MIXED = re.compile(r"[A-Za-z]\d|\d[A-Za-z]")


def is_codey(tok: str) -> bool:
    """True if a token is clearly a code identifier, not an English word."""
    if "_" in tok:
        return True
    if _CAMEL.search(tok):
        return True
    if tok.isupper() and len(tok) >= 2:
        return True
    if _MIXED.search(tok):
        return True
    return len(tok) >= 12


def changed_lines(diff_text: str) -> tuple[list[str], list[str]]:
    """(added, removed) code lines, excluding the +++/--- file headers."""
    added, removed = [], []
    for ln in diff_text.splitlines():
        if ln.startswith("+++") or ln.startswith("---"):
            continue
        if ln.startswith("+"):
            added.append(ln[1:])
        elif ln.startswith("-"):
            removed.append(ln[1:])
    return added, removed


def fix_tokens(diff_text: str) -> dict:
    added, removed = changed_lines(diff_text)
    changed = added + removed
    idents = {t for line in changed for t in _IDENT.findall(line) if is_codey(t)}
    strings = set()
    for line in changed:
        for groups in _STRLIT.findall(line):
            for inner in groups:
                if inner.strip():
                    strings.add(inner.strip().lower())
    nums_added = {n for line in added for n in _NUM.findall(line)}
    nums_removed = {n for line in removed for n in _NUM.findall(line)}
    # Only specific constants count as "naming a constant"; trivial small ints
    # (0/1/2/.. one-digit) are too generic and would false-positive on natural
    # phrasing like "length 0". Keep multi-digit ints and any float.
    new_nums = {n for n in (nums_added - nums_removed) if len(n) >= 2 or "." in n}
    return {"idents": idents, "strings": strings, "nums": new_nums}


def _diag_text(diag: dict) -> str:
    if not diag:
        return ""
    parts = []
    for k in ("summary", "root_cause", "remediation"):
        parts.append(str(diag.get(k, "")))
    ev = diag.get("evidence")
    if isinstance(ev, (list, tuple)):
        parts.extend(str(x) for x in ev)
    elif ev:
        parts.append(str(ev))
    return "\n".join(parts)


def resolve_fix_diff(scenario: dict, repo_root: Path = REPO) -> Path | None:
    sid = scenario.get("scenario_id", "")
    cf = scenario.get("code_fault") or {}
    cands = [
        scenario.get("gold_patch_path", ""),
        f"patches/{sid}_fix.diff",
        f"patches/{cf.get('defect_id', '')}_fix.diff",
        f"patches/github/{sid}.diff",
    ]
    for c in cands:
        if c and (repo_root / c).exists():
            return repo_root / c
    return None


def observable_text(scenario: dict) -> str:
    """Symptom material the agent can already see (issue/test/logs). A fix token
    that already appears here is NOT a leak -- the diagnosis may quote the panic
    message. (Source code is NOT included: the point of the gate is that gold must
    not transcribe the fix construct, even though that construct is in the repo.)"""
    vc = scenario.get("visible_context") or {}
    task = scenario.get("task") or {}
    of = scenario.get("ops_fault") or {}
    parts = [vc.get("issue_text", ""), vc.get("notes", ""),
             task.get("summary", ""), task.get("instructions", ""), task.get("acceptance_notes", "")]
    for k in ("error_logs", "reproduction_steps", "relevant_files"):
        parts.extend(str(x) for x in vc.get(k, []))
    parts.extend(str(x) for x in of.get("detection_keywords", []))
    return "\n".join(parts)


def scan_one(scenario: dict, repo_root: Path, diag: dict) -> dict:
    """Offending tokens for one (scenario, {gold,wrong}) pair. Empty == clean.

    Raises FileNotFoundError when no fix diff resolves: an unchecked diagnosis
    must never look clean to a caller that only counts offending tokens.
    """
    diff_path = resolve_fix_diff(scenario, repo_root)
    if diff_path is None:
        raise FileNotFoundError(
            f"no fix diff found for {scenario.get('scenario_id', '')!r}; cannot check leakage"
        )
    ft = fix_tokens(diff_path.read_text(encoding="utf-8", errors="replace"))
    # Subtract tokens already visible in the observable symptom material.
    obs = observable_text(scenario)
    obs_l = obs.lower()
    obs_idents = {t for t in _IDENT.findall(obs) if is_codey(t)}
    ft_idents = ft["idents"] - obs_idents
    ft_strings = {s for s in ft["strings"] if s not in obs_l}
    ft_nums = {n for n in ft["nums"] if not re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", obs)}
    text = "\n".join(_diag_text(diag.get(k)) for k in ("gold", "wrong"))
    text_l = text.lower()
    diag_idents = {t for t in _IDENT.findall(text) if is_codey(t)}
    off_idents = sorted(ft_idents & diag_idents)
    off_strings = sorted(s for s in ft_strings if s in text_l)
    off_nums = sorted(n for n in ft_nums if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", text))
    return {"idents": off_idents, "strings": off_strings, "nums": off_nums,
            "fix_diff": str(diff_path.relative_to(repo_root))}


def _load_manifest_scenarios(manifests, repo_root: Path) -> list[tuple[str, dict]]:
    out = []
    for man in manifests:
        data = json.loads((repo_root / man).read_text(encoding="utf-8"))
        for e in data["scenarios"]:
            rel = e["scenario"]
            sc = json.loads((repo_root / rel).read_text(encoding="utf-8"))
            out.append((rel, sc))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifests", nargs="*", default=DEFAULT_MANIFESTS)
    ap.add_argument("--diag-dir", default=DEFAULT_DIAG_DIR)
    ap.add_argument("--report", action="store_true", help="list, never fail")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--allow-missing", action="store_true")
    ap.add_argument("--repo", default=str(REPO))
    args = ap.parse_args()
    repo = Path(args.repo)
    diag_dir = repo / args.diag_dir

    scenarios = _load_manifest_scenarios(args.manifests, repo)
    results, leaks, missing, no_diff = [], 0, 0, 0
    for rel, sc in scenarios:
        sid = sc["scenario_id"]
        dpath = diag_dir / f"{sid}.json"
        if not dpath.exists():
            missing += 1
            results.append({"sid": sid, "status": "MISSING"})
            continue
        diag = json.loads(dpath.read_text(encoding="utf-8"))
        try:
            off = scan_one(sc, repo, diag)
        except FileNotFoundError:
            # A diagnosis exists but cannot be checked: always a gate failure,
            # independent of --allow-missing (which covers missing diag files).
            no_diff += 1
            results.append({"sid": sid, "status": "NO_FIX_DIFF"})
            continue
        n = len(off.get("idents", [])) + len(off.get("strings", [])) + len(off.get("nums", []))
        if n:
            leaks += 1
            results.append({"sid": sid, "status": "LEAK", **off})
        else:
            results.append({"sid": sid, "status": "clean", "fix_diff": off.get("fix_diff")})

    if args.json:
        print(json.dumps({"results": results, "leaks": leaks, "missing": missing,
                          "no_fix_diff": no_diff, "total": len(scenarios)}, indent=2))
    else:
        for r in results:
            if r["status"] == "LEAK":
                bits = []
                if r.get("idents"):
                    bits.append(f"idents={r['idents']}")
                if r.get("strings"):
                    bits.append(f"strings={r['strings']}")
                if r.get("nums"):
                    bits.append(f"nums={r['nums']}")
                print(f"  LEAK  {r['sid']}: " + "; ".join(bits))
            elif r["status"] != "clean":
                print(f"  {r['status']}  {r['sid']}")
        clean = sum(1 for r in results if r["status"] == "clean")
        print(f"\n{clean}/{len(scenarios)} clean | {leaks} leaking | {missing} missing | "
              f"{no_diff} no-diff")

    if args.report:
        return 0
    return 1 if (leaks or no_diff or (missing and not args.allow_missing)) else 0


if __name__ == "__main__":
    sys.exit(main())
