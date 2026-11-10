#!/usr/bin/env python3
"""Matched retry-policy outcomes and scenario-cluster sensitivities.

The panel is restricted, within model, to scenarios and candidate-slot keys
present under no retry (NR), generic retry (GR), and available-error retry (ER).
This makes the three terminal-outcome distributions directly comparable.
"""
from __future__ import annotations

import math
import os
import random
import sys
import zlib
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from analyze_fleet import build_data  # noqa: E402
from analyze_retryonly import merge_rows, filter_scenarios, wilson  # noqa: E402

B = 100000
SEED = 20260710
POLICIES = ("NR", "GR", "ER")
CATEGORIES = ("not_applied", "broke_tests", "pass_other", "pass_faster")


def _row_key(row):
    return (row.get("scenario_id"), row.get("arm"), row.get("seed"), row.get("iteration"))


def matched_retry_panel(data=None):
    """Return exact common candidate-slot rows for NR/GR/ER within each model."""
    data = data if data is not None else build_data(verbose=False)
    rc_conditions = sorted({c for (_, c) in data if str(c).lower().startswith("rc")})
    models = sorted({m for (m, c) in data if c == "OFF"} & {m for (m, c) in data if c == "ON"})
    out = []
    for model in models:
        rc_groups = [data[(model, cond)] for cond in rc_conditions if (model, cond) in data]
        if not rc_groups:
            continue
        gr_rows = merge_rows(rc_groups)
        scenarios = sorted({row["scenario_id"] for row in gr_rows})
        policies = {
            "NR": filter_scenarios(data[(model, "OFF")], scenarios),
            "GR": gr_rows,
            "ER": filter_scenarios(data[(model, "ON")], scenarios),
        }
        maps = {policy: {_row_key(row): row for row in rows} for policy, rows in policies.items()}
        common = sorted(set.intersection(*(set(values) for values in maps.values())))
        out.append(dict(
            model=model,
            scenarios=scenarios,
            rows={policy: [maps[policy][key] for key in common] for policy in POLICIES},
        ))
    return out


def _speedup(row):
    try:
        value = float(row.get("measured_speedup") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def terminal_category(row, threshold=0.0):
    if str(row.get("applied")).lower() != "true":
        return "not_applied"
    if str(row.get("correct")).lower() != "true":
        return "broke_tests"
    if _speedup(row) > 1.0 + threshold:
        return "pass_faster"
    return "pass_other"


def _rates(rows, threshold=0.0):
    counts = Counter(terminal_category(row, threshold) for row in rows)
    n = len(rows)
    return {category: counts[category] / n if n else 0.0 for category in CATEGORIES}


def _quantile(values, probability):
    values = sorted(values)
    if not values:
        return 0.0
    position = probability * (len(values) - 1)
    lo, hi = int(math.floor(position)), int(math.ceil(position))
    if lo == hi:
        return values[lo]
    weight = position - lo
    return values[lo] * (1 - weight) + values[hi] * weight


def _cluster_ci(values_by_cluster, seed_key, b=B):
    clusters = sorted(values_by_cluster)
    values = [values_by_cluster[key] for key in clusters]
    mean = sum(values) / len(values) if values else 0.0
    if not values:
        return mean, 0.0, 0.0
    rng = random.Random(SEED + zlib.crc32(seed_key.encode("utf-8")))
    boots = []
    for _ in range(b):
        boots.append(sum(rng.choice(values) for _ in values) / len(values))
    return mean, _quantile(boots, 0.025), _quantile(boots, 0.975)


def _model_scenario_rates(panel, threshold=0.0):
    """Return {(model,scenario,policy): terminal-rate dict}."""
    out = {}
    for record in panel:
        model = record["model"]
        for policy, rows in record["rows"].items():
            grouped = defaultdict(list)
            for row in rows:
                grouped[row["scenario_id"]].append(row)
            for scenario, cell_rows in grouped.items():
                out[(model, scenario, policy)] = _rates(cell_rows, threshold)
    return out


def scenario_balanced_outcomes(panel=None, threshold=0.0, b=B):
    """Equal-weight scenarios after averaging available models within scenario."""
    panel = panel if panel is not None else matched_retry_panel()
    cells = _model_scenario_rates(panel, threshold)
    scenario_rates = defaultdict(lambda: defaultdict(list))
    for (_, scenario, policy), rates in cells.items():
        for category, value in rates.items():
            scenario_rates[(scenario, policy)][category].append(value)

    by_scenario = {}
    for (scenario, policy), category_values in scenario_rates.items():
        by_scenario[(scenario, policy)] = {
            category: sum(values) / len(values)
            for category, values in category_values.items()
        }

    scenarios = sorted({scenario for (scenario, _) in by_scenario})
    levels = {
        policy: {
            category: sum(by_scenario[(scenario, policy)][category] for scenario in scenarios) / len(scenarios)
            for category in CATEGORIES
        }
        for policy in POLICIES
    }
    level_intervals = {}
    for policy in POLICIES:
        for category in CATEGORIES:
            values = {
                scenario: by_scenario[(scenario, policy)][category]
                for scenario in scenarios
            }
            level_intervals[(category, policy)] = _cluster_ci(
                values, f"{threshold}:{category}:{policy}:level", b=b
            )
    differences = {}
    for category in CATEGORIES:
        for policy_a, policy_b in (("GR", "NR"), ("ER", "NR"), ("ER", "GR")):
            values = {
                scenario: by_scenario[(scenario, policy_a)][category]
                - by_scenario[(scenario, policy_b)][category]
                for scenario in scenarios
            }
            differences[(category, policy_a, policy_b)] = _cluster_ci(
                values, f"{threshold}:{category}:{policy_a}:{policy_b}", b=b
            )
    return dict(levels=levels, level_intervals=level_intervals,
                by_scenario=by_scenario, differences=differences, scenarios=scenarios)


def retry_apply_effects(panel=None, b=B):
    """Per-model and pooled ER-minus-GR apply-rate effects."""
    panel = panel if panel is not None else matched_retry_panel()
    cells = _model_scenario_rates(panel, threshold=0.0)
    rows = []
    for record in panel:
        model = record["model"]
        scenarios = record["scenarios"]
        rates = {}
        for policy in POLICIES:
            policy_rows = record["rows"][policy]
            applied = sum(str(row.get("applied")).lower() == "true" for row in policy_rows)
            lo, hi = wilson(applied, len(policy_rows))
            rates[policy] = (applied / len(policy_rows), lo, hi, len(policy_rows))
        diffs = {
            scenario: (1 - cells[(model, scenario, "ER")]["not_applied"])
            - (1 - cells[(model, scenario, "GR")]["not_applied"])
            for scenario in scenarios
        }
        effect = _cluster_ci(diffs, f"apply:{model}", b=b)
        rows.append(dict(model=model, scenarios=len(scenarios), rates=rates, effect=effect))

    pooled_by_scenario = defaultdict(list)
    for record in panel:
        model = record["model"]
        for scenario in record["scenarios"]:
            pooled_by_scenario[scenario].append(
                (1 - cells[(model, scenario, "ER")]["not_applied"])
                - (1 - cells[(model, scenario, "GR")]["not_applied"])
            )
    pooled_values = {scenario: sum(values) / len(values)
                     for scenario, values in pooled_by_scenario.items()}
    # Only point levels are needed here; the pooled effect above carries the CI.
    outcomes = scenario_balanced_outcomes(panel, threshold=0.0, b=0)
    pooled_rates = {
        policy: (1 - outcomes["levels"][policy]["not_applied"], None, None, None)
        for policy in POLICIES
    }
    return dict(rows=rows, pooled=dict(
        scenarios=len(pooled_values), rates=pooled_rates,
        effect=_cluster_ci(pooled_values, "apply:pooled", b=b),
    ))


def model_outcome_shifts(panel=None, threshold=0.05):
    """ER-relative-to-GR favorable rate shifts by model and scenario-balanced pool.

    All three columns use a positive-is-favorable orientation: more applied slots,
    fewer broken-test slots, and more passing slots above ``threshold``.
    """
    panel = panel if panel is not None else matched_retry_panel()
    cells = _model_scenario_rates(panel, threshold=threshold)
    rows = []
    for record in panel:
        model = record["model"]
        scenarios = record["scenarios"]
        shifts = {
            "applied": [],
            "avoided_broken": [],
            "pass_faster": [],
        }
        for scenario in scenarios:
            gr = cells[(model, scenario, "GR")]
            er = cells[(model, scenario, "ER")]
            shifts["applied"].append((1 - er["not_applied"]) - (1 - gr["not_applied"]))
            shifts["avoided_broken"].append(gr["broke_tests"] - er["broke_tests"])
            shifts["pass_faster"].append(er["pass_faster"] - gr["pass_faster"])
        rows.append(dict(
            model=model,
            scenarios=len(scenarios),
            shifts={key: sum(values) / len(values) for key, values in shifts.items()},
        ))

    pooled = scenario_balanced_outcomes(panel, threshold=threshold, b=0)["levels"]
    rows.append(dict(
        model="__pooled__",
        scenarios=len({scenario for record in panel for scenario in record["scenarios"]}),
        shifts={
            "applied": (1 - pooled["ER"]["not_applied"]) - (1 - pooled["GR"]["not_applied"]),
            "avoided_broken": pooled["GR"]["broke_tests"] - pooled["ER"]["broke_tests"],
            "pass_faster": pooled["ER"]["pass_faster"] - pooled["GR"]["pass_faster"],
        },
    ))
    return rows


def model_outcome_effects(panel=None, threshold=0.05, b=B):
    """ER-minus-GR rate contrasts and scenario-bootstrap 95% intervals.

    Every outcome uses all matched rounds as its denominator. A negative
    failed-test contrast means fewer failures, not necessarily better
    correctness among applied patches. Existing point estimates are preserved.
    """
    panel = panel if panel is not None else matched_retry_panel()
    cells = _model_scenario_rates(panel, threshold=threshold)
    application = retry_apply_effects(panel, b=b)
    apply_by_model = {row["model"]: row["effect"] for row in application["rows"]}
    rows = []
    for record in panel:
        model = record["model"]
        effects = {"applied": apply_by_model[model]}
        for category in ("broke_tests", "pass_faster"):
            differences = {
                scenario: cells[(model, scenario, "ER")][category]
                - cells[(model, scenario, "GR")][category]
                for scenario in record["scenarios"]
            }
            effects[category] = _cluster_ci(
                differences, f"{threshold}:{category}:{model}:ER:GR", b=b
            )
        rows.append(dict(model=model, scenarios=len(record["scenarios"]), effects=effects))

    pooled = scenario_balanced_outcomes(panel, threshold=threshold, b=b)
    rows.append(dict(
        model="__pooled__", scenarios=len(pooled["scenarios"]), effects={
            "applied": application["pooled"]["effect"],
            **{category: pooled["differences"][(category, "ER", "GR")]
               for category in ("broke_tests", "pass_faster")},
        },
    ))
    return rows


def raw_counts(panel=None, threshold=0.0):
    panel = panel if panel is not None else matched_retry_panel()
    out = {}
    for policy in POLICIES:
        rows = [row for record in panel for row in record["rows"][policy]]
        counts = Counter(terminal_category(row, threshold) for row in rows)
        out[policy] = dict(n=len(rows), **{category: counts[category] for category in CATEGORIES})
    return out


def main():
    panel = matched_retry_panel()
    effects = retry_apply_effects(panel)
    print("=== Matched retry apply rates and ER-GR scenario-cluster effects ===")
    for row in effects["rows"] + [dict(model="POOLED", **effects["pooled"])]:
        rates = row["rates"]
        effect = row["effect"]
        print(f"{row['model']:17s} nscen={row['scenarios']:2d} "
              f"NR={rates['NR'][0]:.3f} GR={rates['GR'][0]:.3f} ER={rates['ER'][0]:.3f} "
              f"ER-GR={effect[0]:+.4f} [{effect[1]:+.4f},{effect[2]:+.4f}]")
    for threshold in (0.0, 0.01, 0.05, 0.10):
        result = scenario_balanced_outcomes(panel, threshold=threshold)
        print(f"\n=== Scenario-balanced terminal outcomes, threshold >{threshold:.0%} ===")
        for policy in POLICIES:
            print(policy, " ".join(f"{key}={value:.4f}" for key, value in result["levels"][policy].items()))
        print("ER-GR pass_faster", result["differences"][("pass_faster", "ER", "GR")])
    print("\n=== ER-relative-to-GR favorable shifts at >5% ===")
    for row in model_outcome_shifts(panel):
        print(row["model"], " ".join(
            f"{key}={100 * value:+.2f}pp" for key, value in row["shifts"].items()
        ))


if __name__ == "__main__":
    main()
