"""Turn a study result into the published bundle: CSVs, the figure, two Markdown reports,
summary.json and run_manifest.json, written to a staging folder and swapped into place only
when complete. The reports' fixed prose lives in templates/; every number and every
sentence whose wording depends on a result's sign is generated here.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import shutil
import string
from fractions import Fraction
from importlib import metadata
from pathlib import Path

import matplotlib
import matplotlib.dates as mdates
import matplotlib.style
import pandas as pd
from matplotlib.figure import Figure

import experiment
import model

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
SOURCES = ("src/data.py", "src/model.py", "src/experiment.py", "src/report.py", "src/replenishment.py",
           "data/code_registry.csv", "templates/insight_report.md", "templates/data_quality.md",
           "templates/readme_results.md")
PACKAGES = ("numpy", "pandas", "openpyxl", "matplotlib")
SCHEMA_VERSION = 1
FIGURE = "cost_difference.svg"
CSVS = ("policy_comparison.csv", "sku_decisions.csv", "forecast_metrics.csv", "weekly_results.csv",
        "sensitivity.csv", "published_bridge.csv", "reconciliation.csv", "reversal_pairs.csv", "weekly_sales.csv")
ARTIFACTS = CSVS + (FIGURE, "insight_report.md", "data_quality.md", "summary.json")
MANIFEST = "run_manifest.json"
NAMES = experiment.POLICIES
PHRASES = {  # policy names inside sentences
    "proportional": "proportional allocation", "scaled_fractile": "the scaled critical-fractile rule",
    "optimizer": "the marginal optimizer", "optimizer_unit": "the equal-price optimizer",
    "unconstrained": "the unconstrained newsvendor",
}
README_START, README_END = "<!-- results:start -->", "<!-- results:end -->"


# Wording ----------------------------------------------------------------------------------


def money(value) -> str:
    return "n/a" if value is None or not math.isfinite(value) else f"{'−' if value < 0 else ''}£{abs(value):,.0f}"


def pct(value, digits=1) -> str:
    return "n/a" if value is None or not math.isfinite(value) else f"{value:.{digits}%}".replace("-", "−")


def day(value, days=0) -> str:
    return (pd.Timestamp(value) + pd.Timedelta(days, "D")).strftime("%-d %B %Y")


def undefined(value) -> bool:
    return value is None or not math.isfinite(value)


def change(value) -> str:
    """A relative difference in words: '4.0% higher', '1.3% lower', 'equal'."""
    if undefined(value) or value == 0:
        return "n/a" if undefined(value) else "equal"
    return f"{pct(abs(value)) if round(abs(value), 3) else 'less than 0.1%'} {'lower' if value < 0 else 'higher'}"


def signed(value) -> str:
    """A relative difference for tables: '+4.0%', '−1.3%'."""
    return pct(value) if undefined(value) or round(abs(value), 3) == 0 else ("+" if value > 0 else "") + pct(value)


def interval(values) -> str:
    return f"{signed(values[0])} to {signed(values[1])}"


def compared(value, name: str) -> str:
    """'4.0% higher than X', 'equal to X', or a note that X's cost is zero."""
    if undefined(value):
        return f"not comparable in relative terms with {name}, which is zero"
    return f"equal to {name}" if value == 0 else f"{change(value)} than {name}"


def table(rows, header, align: str) -> str:
    """A Markdown table; `align` holds 'l' or 'r' per column."""
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---:" if a == "r" else "---" for a in align) + " |"]
    return "\n".join(lines + ["| " + " | ".join(str(cell).replace("|", "/") for cell in row) + " |" for row in rows])


def verdict(comparison) -> str:
    low, high = comparison["interval"]["relative"]
    if undefined(low) or undefined(high):  # a resampled baseline cost of zero
        low, high = comparison["interval"]["difference"]
    return "lower" if high < 0 else "higher" if low > 0 else "no clear difference"


def describe(comparison, weeks: int, lead: bool = True) -> str:
    """One sign-aware sentence for a paired comparison of total modeled cost; `lead`
    names the policy, otherwise the sentence continues from one that did."""
    baseline = PHRASES[comparison["baseline"]] + "'s"
    rel, (low, high), kind = comparison["relative"], comparison["interval"]["relative"], verdict(comparison)
    counts = (f"it cost less in {comparison['weeks_won']} of the {weeks} weeks and more in "
              f"{comparison['weeks_lost']}" + (f", the same in {comparison['weeks_tied']}"
                                               if comparison["weeks_tied"] else ""))
    level = int(round(comparison["confidence"] * 100))
    if low == high == 0:
        spread = f"the same in every resample; {counts}"
    elif undefined(low) or undefined(high):
        low, high = comparison["interval"]["difference"]
        spread = f"{level}% interval of the difference {money(low)} to {money(high)}; {counts}"
    elif kind == "no clear difference":
        spread = f"{level}% interval from {change(low)} to {change(high)}; {counts}"
    else:
        ends = sorted([abs(low), abs(high)])
        spread = f"{level}% interval {pct(ends[0])} to {pct(ends[1])} {kind}; {counts}"
    unclear = kind == "no clear difference"
    if lead:
        subject = PHRASES[comparison["policy"]] + "'s"
        total = compared(rel, baseline)
        return (f"{subject[0].upper()}{subject[1:]} modeled cost was {total}"
                + (", with no clear difference" if unclear else "") + f" ({spread}).")
    total = ("equal in total" if rel == 0 else "not comparable in relative terms" if undefined(rel)
             else change(rel) + (" in total" if unclear else ""))
    opening = "there was no clear difference:" if unclear else "it was"
    return f"Against {PHRASES[comparison['baseline']]}, {opening} {total} ({spread})."


# Summary ----------------------------------------------------------------------------------


def _plain(value):
    """JSON-ready values: dates as ISO days, NaN as null, floats rounded to 6 places."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d") if value == value.normalize() else value.isoformat()
    if hasattr(value, "item"):  # NumPy scalars
        value = value.item()
    if isinstance(value, float):
        return round(value, 6) if math.isfinite(value) else None
    return value


def _comparisons(items, config) -> list:
    out = []
    for item in items:
        entry = {key: item[key] for key in ("baseline", "policy_cost", "baseline_cost", "difference", "relative",
                                            "weeks_won", "weeks_lost", "weeks_tied")}
        entry.update(policy="optimizer", confidence=float(config.confidence), block_weeks=config.block_weeks,
                     interval=item["intervals"][config.block_weeks])
        entry["checks"] = [{"block_weeks": block, **values} for block, values in item["intervals"].items()
                           if block != config.block_weeks]
        entry["verdict"] = verdict(entry)
        out.append(entry)
    return out


def _policies(scenario_result) -> list:
    return [{"id": policy, "name": NAMES[policy], "reference": policy in experiment.REFERENCES,
             **experiment.policy_summary(run, scenario_result.capacity)}
            for policy, run in scenario_result.runs.items()]


def best_within_capacity(policies) -> str:
    feasible = [row for row in policies if not row["reference"] and row["within_capacity"]]
    return min(feasible, key=lambda row: row["total_cost"])["id"]


def scenario_settings(scenario: experiment.Scenario) -> dict:
    return {"id": scenario.id, "label": scenario.label, "window": scenario.window,
            "closure_weeks": scenario.closures, "capacity_factor": float(scenario.capacity_factor),
            "holding_rate": float(scenario.holding_rate), "shortage_rate": float(scenario.shortage_rate),
            "critical_ratio": float(scenario.critical_ratio),
            "bulk_cap_quantile": None if scenario.bulk_cap is None else float(scenario.bulk_cap),
            **vars(scenario.rules)}


def summarize(result: experiment.Result) -> dict:
    """The one summary every report and the README block are rendered from."""
    config, study, primary, tables = result.config, result.study, result.primary, result.tables
    weeks, policies = study.evaluation, _policies(primary)
    sensitivity = [{**scenario_settings(item.scenario), "capacity_units": item.capacity,
                    "costs": {row["id"]: row["total_cost"] for row in _policies(item)},
                    "best_within_capacity": best_within_capacity(_policies(item)),
                    "comparisons": _comparisons(item.comparisons, config)} for item in result.scenarios]
    pairs = tables["pairs"]
    local = pairs.loc[pairs["sale_country"].eq(config.country)]
    in_cohort = local["sku"].isin(study.cohort)
    return _plain({
        "schema_version": SCHEMA_VERSION,
        "study": {
            "country": config.country, "skus": list(study.cohort), "cohort_size": len(study.cohort),
            "capacity_units": primary.capacity, "mean_weekly_units": float(study.mean_units),
            "capacity_factor": float(config.primary.capacity_factor),
            "selection": {"first_week": study.selection[0], "last_week": study.selection[-1],
                          "weeks": len(study.selection), "open_weeks": len(study.selection.difference(study.closures))},
            "evaluation": {"first_week": weeks[0], "last_day": weeks[-1] + pd.Timedelta(6, "D"),
                           "weeks": len(weeks), "closure_weeks": list(weeks.intersection(study.closures))},
            "holding_rate": float(config.primary.holding_rate), "shortage_rate": float(config.primary.shortage_rate),
            "critical_ratio": float(config.primary.critical_ratio), "window": config.primary.window,
            "window_label": experiment.WINDOWS[config.primary.window][0], "min_active_weeks": config.min_active_weeks,
            "decision_week": result.decisions["decision_week"].iloc[0],
        },
        "settings": {"reversal_hours": config.reversal_hours, "block_weeks": config.block_weeks,
                     "resamples": config.resamples, "bridge_sheet": config.bridge_sheet,
                     "bridge_holdout_weeks": config.bridge_holdout_weeks,
                     "bridge_min_active_weeks": config.bridge_min_active_weeks,
                     "bridge_capacity_share": float(config.bridge_capacity_share)},
        "policies": policies,
        "best_within_capacity": best_within_capacity(policies),
        "comparisons": _comparisons(primary.comparisons, config),
        "quarters": experiment.quarters(primary).to_dict("records"),
        "sku_contributions": experiment.sku_contributions(primary).to_dict("records"),
        "sensitivity": sensitivity,
        "bridge": result.bridge.drop(columns=["cohort"]).to_dict("records"),
        "forecasts": result.forecasts.to_dict("records"),
        "largest_week": result.largest,
        "data": {
            "sheets": result.sheets, "country_stages": tables["stages"].to_dict("records"),
            "prompt_pairs": len(pairs), "country_prompt_pairs": len(local),
            "country_prompt_units": int(local["units"].sum()), "cohort_prompt_pairs": int(in_cohort.sum()),
            "cohort_prompt_units": int(local.loc[in_cohort, "units"].sum()),
            "largest_prompt_pairs": local.nlargest(5, "units")[["sku", "units", "sale_invoice", "credit_invoice",
                                                               "sale_time", "lag_minutes"]].to_dict("records"),
            "closure_weeks": list(study.closures), "first_complete_week": study.complete[0],
            "last_complete_week": study.complete[-1],
            "partial_weeks": list(study.calendar.loc[~study.calendar["complete"], "week_start"]),
        },
    })


def console_line(summary: dict, output) -> str:
    """The run's one-line console report: the best policy within capacity, the reference apart."""
    best = next(row for row in summary["policies"] if row["id"] == summary["best_within_capacity"])
    line = (f"wrote {output} | {summary['study']['cohort_size']} SKUs | capacity {summary['study']['capacity_units']:,} "
            f"units | lowest modeled cost within capacity: {best['name']} ({money(best['total_cost'])})")
    return line + "".join(f" | reference without the limit: {row['name']} ({money(row['total_cost'])})"
                          for row in summary["policies"] if row["reference"])


# CSVs and the figure ----------------------------------------------------------------------


def frames(result: experiment.Result) -> dict:
    """Every published CSV as a frame, keyed by file name."""
    config, primary, tables = result.config, result.primary, result.tables
    columns = ("allocated_units", "fill_rate", "stockout_rate", "holding_cost", "shortage_cost", "total_cost")
    comparison = pd.DataFrame([{"policy": row["name"], **{key: row[key] for key in columns}, "policy_id": row["id"],
                                "within_capacity": row["within_capacity"], "capacity_units": primary.capacity,
                                "ordered_units": row["ordered_units"], "leftover_units": row["leftover_units"],
                                "reference": row["reference"]} for row in _policies(primary)])
    weekly = []
    for policy, run in primary.runs.items():
        records = pd.DataFrame(run.records())
        records.insert(0, "policy_id", policy)
        records["week"] = primary.weeks[records["week"].to_numpy()]
        records.insert(3, "price", primary.prices.ravel())
        weekly.append(records.rename(columns={"week": "week_start"}))
    sensitivity = []
    for item in result.scenarios:
        rows = _policies(item)
        row = {**scenario_settings(item.scenario), "capacity_units": item.capacity,
               **{f"{policy['id']}_cost": policy["total_cost"] for policy in rows}}
        for entry in item.comparisons:
            name = f"optimizer_vs_{entry['baseline']}"
            low, high = entry["intervals"][config.block_weeks]["relative"]
            row.update({name: entry["relative"], f"{name}_low": low, f"{name}_high": high,
                        f"{name}_weeks_won": entry["weeks_won"], f"{name}_weeks_lost": entry["weeks_lost"]})
        sensitivity.append({**row, "best_within_capacity": best_within_capacity(rows)})
    return {
        "policy_comparison.csv": comparison, "sku_decisions.csv": result.decisions,
        "forecast_metrics.csv": result.forecasts, "weekly_results.csv": pd.concat(weekly, ignore_index=True),
        "sensitivity.csv": pd.DataFrame(sensitivity).rename(columns={"id": "scenario"}),
        "published_bridge.csv": result.bridge, "reconciliation.csv": tables["reconciliation"],
        "reversal_pairs.csv": tables["pairs"], "weekly_sales.csv": tables["weekly_sales"],
    }


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    """Datetime columns as whole days (YYYY-MM-DD) or times to the second."""
    frame = frame.copy()
    for column in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            stamps = frame[column].dropna()
            frame[column] = frame[column].dt.strftime(
                "%Y-%m-%d" if stamps.eq(stamps.dt.normalize()).all() else "%Y-%m-%d %H:%M:%S")
    frame.to_csv(path, index=False, lineterminator="\n")


def weekly_cost(scenario_result) -> pd.DataFrame:
    """Each policy's total modeled cost per evaluation week."""
    return pd.DataFrame({policy: run.cost.sum(axis=1) for policy, run in scenario_result.runs.items()},
                        index=scenario_result.weeks.rename("week_start"))


def cost_difference(weekly_cost: pd.DataFrame, reference="optimizer", baselines=("scaled_fractile", "proportional")):
    """Cumulative (reference - baseline) cost per week; index week_start, one column per baseline id."""
    return pd.DataFrame({baseline: weekly_cost[reference] - weekly_cost[baseline] for baseline in baselines}).cumsum()


def write_cost_difference_figure(weekly_cost: pd.DataFrame, names, path: Path, reference="optimizer",
                                 baselines=("scaled_fractile", "proportional")) -> None:
    """The SVG of the reference policy's cumulative weekly modeled cost minus each baseline's.

    Matplotlib's default style with a fixed hash salt, text kept as text and no date, so
    the same data always gives the same file."""
    lines = cost_difference(weekly_cost, reference, baselines)
    count, subject = len(lines), names[reference][:1].lower() + names[reference][1:]
    with matplotlib.style.context("default"), matplotlib.rc_context({"svg.hashsalt": "cost-difference",
                                                                      "svg.fonttype": "none"}):
        figure = Figure(figsize=(9, 5), layout="constrained")
        axes = figure.subplots()
        for baseline in baselines:
            axes.plot(lines.index, lines[baseline], marker=".",
                      label=f"minus {names[baseline]}: {money(lines[baseline].iloc[-1])} at the end")
        axes.axhline(0, color="black", linewidth=0.8)
        axes.xaxis.set_major_formatter(mdates.ConciseDateFormatter(axes.xaxis.get_major_locator()))
        axes.grid(alpha=0.3)
        axes.legend(title=names[reference])
        axes.set(xlabel="Week starting", ylabel="Cumulative difference in modeled cost (£)",
                 title=f"{names[reference]} minus each baseline, {day(lines.index[0])} to {day(lines.index[-1], 6)} "
                       f"({count} week{'s' if count != 1 else ''})\nAbove zero, the {subject} has cost more so far; "
                       f"below zero, less")
        figure.savefig(path, format="svg", metadata={"Date": None, "Creator": None})


# Reports ----------------------------------------------------------------------------------


def render(name: str, values) -> str:
    return string.Template((TEMPLATES / name).read_text(encoding="utf-8")).substitute(values)


def _policy_rows(summary, compact=False):
    rows = []
    for row in summary["policies"]:
        name = row["name"] + (" (reference, ignores the limit)" if row["reference"] else "")
        cells = [money(row["total_cost"]), pct(row["fill_rate"]), f"{row['leftover_units']:,.0f}"]
        if not compact:
            cells = ["yes" if row["within_capacity"] else "no", money(row["total_cost"]), money(row["holding_cost"]),
                     money(row["shortage_cost"]), pct(row["fill_rate"]), pct(row["stockout_rate"]),
                     f"{row['allocated_units']:,.0f}", f"{row['leftover_units']:,.0f}", f"{row['ordered_units']:,}"]
        rows.append([name] + cells)
    return rows


def _headline(summary) -> str:
    evaluation, weeks = summary["study"]["evaluation"], summary["study"]["evaluation"]["weeks"]
    first = describe(summary["comparisons"][0], weeks)
    sentences = [f"Over the {weeks} evaluation weeks, {day(evaluation['first_week'])} to "
                 f"{day(evaluation['last_day'])}, {first[0].lower()}{first[1:]}"]
    sentences += [describe(comparison, weeks, lead=False) for comparison in summary["comparisons"][1:]]
    best = next(row for row in summary["policies"] if row["id"] == summary["best_within_capacity"])
    text = f"The lowest modeled cost within the limit was {PHRASES[best['id']]}'s ({money(best['total_cost'])})"
    text += "".join(f"; {PHRASES[row['id']]}, which ignores the limit, came to {money(row['total_cost'])}"
                    for row in summary["policies"] if row["reference"])
    return " ".join(sentences + [text + "."])


def _bridge_sentence(summary, compact=False) -> str:
    """The bridge in words; `compact` (the README, whose table has no scaled column) leaves out
    the comparison with the scaled critical-fractile rule. Steps that left the products, the
    capacity and every cost as in the row before are named."""
    bridge = summary["bridge"]
    first, last = bridge[0], bridge[-1]
    proportional, scaled = PHRASES["proportional"] + "'s", PHRASES["scaled_fractile"] + "'s"
    text = (f"Rerun as originally designed, {PHRASES['optimizer']}'s modeled cost was "
            f"{compared(first['optimizer_vs_proportional'], proportional)}.")
    if len(bridge) > 1:
        text += (f" With all {len(bridge) - 1} corrections applied, it was "
                 f"{compared(last['optimizer_vs_proportional'], proportional)}"
                 + ("." if compact else f" and {compared(last['optimizer_vs_scaled_fractile'], scaled)}."))
    same = ("skus", "capacity_units", "optimizer_cost", "scaled_fractile_cost", "proportional_cost")
    unchanged = [f'"{row["label"]}"' for before, row in zip(bridge, bridge[1:])
                 if not row["skus_added"] and not row["skus_removed"] and all(row[k] == before[k] for k in same)]
    if unchanged:
        steps = unchanged[0] if len(unchanged) == 1 else ", ".join(unchanged[:-1]) + " and " + unchanged[-1]
        text += (f" The step{'s' if len(unchanged) > 1 else ''} {steps} left the products, the capacity and "
                 f"every cost as in the row before.")
    return text


def _bridge_table(summary, compact=False) -> str:
    rows = []
    for row in summary["bridge"]:
        changes = [f"+{row['skus_added']}" if row["skus_added"] else "",
                   f"−{row['skus_removed']}" if row["skus_removed"] else ""]
        rows.append([row["label"], f"{row['train_weeks']} / {row['holdout_weeks']}", f"{row['capacity_units']:,}"]
                    + ([] if compact else [" ".join(filter(None, changes)).replace(" ", ", ") or "none"])
                    + [money(row[f"{policy}_cost"]) for policy in ("optimizer", "scaled_fractile", "proportional")]
                    + [change(row["optimizer_vs_proportional"])])
    header = (["Step", "Training / holdout weeks", "Capacity"] + ([] if compact else ["Cohort changes"])
              + ["Marginal optimizer", "Scaled critical-fractile", "Proportional", "Optimizer vs proportional"])
    return table(rows, header, "lrr" + ("" if compact else "l") + "rrrr")


def _sensitivity(summary):
    """The sensitivity table and a sentence counting the clear and unclear differences."""
    rows, counts = [], {}
    for index, entry in enumerate(summary["sensitivity"]):
        rows.append([entry["label"], f"{entry['capacity_units']:,}"]
                    + [f"{signed(item['relative'])} ({interval(item['interval']['relative'])})"
                       for item in entry["comparisons"]] + [NAMES[entry["best_within_capacity"]]])
        for item in entry["comparisons"] if index else []:
            counts[item["baseline"], item["verdict"]] = counts.get((item["baseline"], item["verdict"]), 0) + 1
    comparisons = summary["comparisons"]
    header = (["Scenario", "Capacity"] + [f"Optimizer vs {NAMES[c['baseline']].lower()}" for c in comparisons]
              + ["Lowest cost within the limit"])
    parts = []
    for number, item in enumerate(comparisons):
        lower, higher, unclear = (counts.get((item["baseline"], kind), 0)
                                  for kind in ("lower", "higher", "no clear difference"))
        name = PHRASES[item["baseline"]]
        found = [(f"clearly {kind}", "than", count) for kind, count in (("lower", lower), ("higher", higher)) if count]
        found += [("not clearly different", "from", unclear)] if unclear else []
        found += [(f"never clearly {kind}", "than", None) for kind, count in (("lower", lower), ("higher", higher))
                  if not count]
        words = [phrase + (f" {preposition} {name}'s" if number == 0 and index == 0 else "")
                 + ("" if count is None else f" in {count}")
                 for index, (phrase, preposition, count) in enumerate(found)]
        listed = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
        parts.append(listed if number == 0 else f"against {name}, {listed}")
    others = len(summary["sensitivity"]) - 1
    sentence = (f"Across the {others} sensitivities, {PHRASES[comparisons[0]['policy']]}'s modeled cost was "
                + "; ".join(parts) + ".") if others else ""
    return table(rows, header, "lr" + "r" * len(comparisons) + "l"), sentence


def _largest(summary) -> str:
    item, credit = summary["largest_week"], summary["largest_week"]["credit"]
    text = (f"The largest single week for a cohort product, relative to its typical selling week, was "
            f"{item['units']:,} units of {item['sku']} ({item['description']}) in the week of {day(item['week'])}, "
            f"{item['ratio']:,.0f} times its median selling week of {item['typical_units']:,.0f} units. Its largest "
            f"line was invoice {item['invoice']} ({item['line_units']:,} units, "
            f"{'no customer recorded' if item['anonymous'] else 'a known customer'}).")
    if credit:
        return text + (f" That line was later matched by credit {credit['invoice']}, {credit['lag_days']:,.1f} days "
                       f"after the sale; credits later than a day stay in the credit ledger and are not removed "
                       f"from sales.")
    return text + " No credit matches that line under the exact-matching rule."


def _quarters(quarters) -> str:
    """How many weeks the quarters hold: 13 each, except a shorter last one."""
    size, last = experiment.QUARTER_WEEKS, quarters[-1]["weeks"]
    weeks = f"{last} week" + ("" if last == 1 else "s")
    if last == size:
        return f"Each quarter is {size} consecutive evaluation weeks."
    if len(quarters) == 1:
        return f"The evaluation is one quarter of {weeks}."
    return f"Each quarter is {size} consecutive evaluation weeks, except the last, which has {weeks}."


def _ratio(study) -> str:
    """The critical ratio to four places, with its exact fraction when the four places round it.

    The summary keeps rates and ratio to six places, so the fraction is worked out from the
    rates and shown only when it reproduces the summary's ratio."""
    ratio = study["critical_ratio"]
    text = f"{ratio:.4f}"
    try:
        exact = model.critical_ratio(study["holding_rate"], study["shortage_rate"])
    except ValueError:  # rates that round to zero
        return text
    shown = exact.denominator <= 1000 and Fraction(text) != exact and round(float(exact), 6) == ratio
    return text + (f" ({exact.numerator}/{exact.denominator})" if shown else "")


def insight_values(summary: dict) -> dict:
    study, settings, comparisons = summary["study"], summary["settings"], summary["comparisons"]
    policy, level = comparisons[0]["policy"], int(round(comparisons[0]["confidence"] * 100))
    feasible = [row["id"] for row in summary["policies"] if not row["reference"]]
    differences = [f"Optimizer minus {NAMES[c['baseline']].lower()}" for c in comparisons]
    comparison_rows = [[f"Optimizer vs {NAMES[item['baseline']].lower()}", money(item["policy_cost"]),
                        money(item["baseline_cost"]), money(item["difference"]), signed(item["relative"]),
                        interval(item["interval"]["relative"]),
                        "; ".join(f"{check['block_weeks']}-week blocks: {interval(check['relative'])}"
                                  for check in item["checks"]) or "none",
                        f"{item['weeks_won']} / {item['weeks_lost']}"
                        + (f" / {item['weeks_tied']}" if item["weeks_tied"] else "")] for item in comparisons]
    quarter_rows = [[f"{q['quarter']} ({day(q['first_week'])} to {day(q['last_week'], 6)})"]
                    + [money(q[p]) for p in feasible] + [money(q[policy] - q[c["baseline"]]) for c in comparisons]
                    for q in summary["quarters"]]
    skus = sorted(summary["sku_contributions"],
                  key=lambda row: -(row[f"{policy}_cost"] - row[f"{comparisons[0]['baseline']}_cost"]))
    sku_rows = [[row["sku"], f"{row['sales_units']:,}"] + [money(row[f"{p}_cost"]) for p in feasible]
                + [money(row[f"{policy}_cost"] - row[f"{c['baseline']}_cost"]) for c in comparisons] for row in skus]
    forecast_rows = [[row["method"], pct(row["wape"]), pct(row["bias"]), f"{row['mae']:,.1f}",
                      f"{row['pinball_loss']:,.1f}"] for row in summary["forecasts"]]
    sensitivity_table, sensitivity_sentence = _sensitivity(summary)
    numbers = "r" * (len(feasible) + len(differences))
    return {
        "headline": _headline(summary), "country": study["country"], "cohort_size": study["cohort_size"],
        "capacity": f"{study['capacity_units']:,}",
        "capacity_basis": ("" if study["capacity_factor"] == 1 else f"{study['capacity_factor']:g} times ")
        + f"the cohort's mean weekly sales ({study['mean_weekly_units']:,.1f} units)",
        "selection_weeks": study["selection"]["weeks"], "open_selection_weeks": study["selection"]["open_weeks"],
        "selection_first": day(study["selection"]["first_week"]), "selection_last": day(study["selection"]["last_week"], 6),
        "evaluation_first": day(study["evaluation"]["first_week"]), "evaluation_last": day(study["evaluation"]["last_day"]),
        "evaluation_weeks": study["evaluation"]["weeks"], "holding_pct": pct(study["holding_rate"]),
        "shortage_pct": pct(study["shortage_rate"]), "critical_ratio": _ratio(study),
        "window_label": study["window_label"].lower(), "min_active_weeks": study["min_active_weeks"],
        "confidence": f"{level}%", "block_weeks": comparisons[0]["block_weeks"],
        "policy_table": table(_policy_rows(summary), ["Policy", "Within the limit", "Modeled cost", "Holding",
                                                      "Shortage", "Fill rate", "SKU-weeks short", "Mean start stock",
                                                      "Mean leftover", "Units ordered"], "llrrrrrrrr"),
        "comparison_table": table(comparison_rows, ["Comparison", "Optimizer", "Baseline", "Difference", "Relative",
                                                    f"{level}% interval", "Interval checks",
                                                    "Weeks lower / higher"], "lrrrrrll"),
        "quarter_sentence": _quarters(summary["quarters"]),
        "quarter_table": table(quarter_rows, ["Quarter"] + [NAMES[p] for p in feasible] + differences, "l" + numbers),
        "sku_table": table(sku_rows, ["SKU", "Sales units"] + [NAMES[p] for p in feasible] + differences,
                           "lr" + numbers),
        "sensitivity_table": sensitivity_table, "sensitivity_sentence": sensitivity_sentence,
        "bridge_sentence": _bridge_sentence(summary), "bridge_table": _bridge_table(summary),
        "forecast_table": table(forecast_rows, ["History window", "WAPE", "Bias", "MAE (units)",
                                                "Pinball loss (units)"], "lrrrr"),
        "largest_week": _largest(summary), "figure": FIGURE, "reversal_hours": settings["reversal_hours"],
        "resamples": f"{settings['resamples']:,}", "bridge_sheet": settings["bridge_sheet"],
        "bridge_holdout_weeks": settings["bridge_holdout_weeks"],
        "bridge_min_active_weeks": settings["bridge_min_active_weeks"],
        "bridge_share": pct(settings["bridge_capacity_share"], 0),
        "decision_week": day(study["decision_week"]),
        "decision_note": (", which is also the workbook's last, partial week"
                          if study["decision_week"] in summary["data"]["partial_weeks"] else ""),
    }


def _cell(column: str, value) -> str:
    """A data-report cell: counts with separators, values in pounds, shares in percent."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if column in ("value", "revenue"):
        return f"£{value:,.2f}".replace("£-", "−£")
    if column.endswith("share"):
        return pct(value)
    if column.endswith("_time"):
        return str(value).replace("T", " ")[:16]
    if column.endswith("_seen"):
        return day(value)
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return f"{int(value):,}".replace("-", "−")
    return f"{value:,.0f}" if isinstance(value, float) else str(value)


def _frame_table(frame, columns: dict) -> str:
    """A Markdown table of `frame`; `columns` maps each column to its header (text left, numbers right)."""
    rows = [[_cell(column, record[column]) for column in columns] for record in frame.to_dict("records")]
    align = "".join("r" if pd.api.types.is_numeric_dtype(frame[column]) else "l" for column in columns)
    return table(rows, list(columns.values()), align) if rows else "None."


def quality_values(summary: dict, tables: dict) -> dict:
    data, study = summary["data"], summary["study"]
    sheets, lines = data["sheets"], {"rows": "Lines", "units": "Units"}
    specs = {
        "selection": {"sku": "SKU", "description": "Description", "active_weeks": "Weeks sold", "units": "Units",
                      "revenue": "Revenue"},
        "reconciliation": {"sheet": "Sheet", "role": "Role", "rows": "Rows", "units": "Units", "value": "Value"},
        "stage": {"stage": "Stage", **lines, "value": "Value"},
        "credit": {"status": "Status", "lag_bucket": "Lag", "credits": "Credits", "units": "Units", "value": "Value",
                   "reinvoice_candidates": "Re-invoiced", "reinvoiced_units": "Re-invoiced units"},
        "registry": {"code": "Code", "code_class": "Class", "code_action": "Action", **lines, "value": "Value",
                     "description": "Description"},
        "unusual": {"sku": "Code", **lines, "description": "Description"},
        "alias": {"sku": "SKU", "stock_code": "Written as", **lines},
        "drift": {"sku": "SKU", "description": "Description", **lines, "first_seen": "First seen",
                  "last_seen": "Last seen"},
        "concentration": {"sku": "SKU", "units": "Units", "customers": "Customers", "anonymous_share": "Anonymous",
                          "top_customer_share": "Top customer", "top_invoice_share": "Top invoice"},
        "repeated": {"sheet": "Sheet", "rows": "Rows", "repeated_rows": "Repeated rows",
                     "repeated_units": "Units on repeated rows"},
    }
    sources = {"stage": "stages", "credit": "credits", "alias": "aliases"}
    values = {f"{name}_table": _frame_table(tables[sources.get(name, name)], columns) for name, columns in specs.items()}
    values["largest_pairs_table"] = _frame_table(pd.DataFrame(data["largest_prompt_pairs"]), {
        "sku": "SKU", "units": "Units", "sale_invoice": "Sale", "credit_invoice": "Credit", "sale_time": "Sale time",
        "lag_minutes": "Minutes later"})
    return values | {
        "sheet_rows": ", ".join(f"{name}: {rows:,}" for name, rows in sheets["rows"].items()),
        "overlap_rows": f"{sheets['overlap_rows']:,}", "combined_rows": f"{sheets['combined_rows']:,}",
        "source_rows": f"{sum(sheets['rows'].values()):,}", "country": study["country"],
        "reversal_hours": summary["settings"]["reversal_hours"], "cohort_size": study["cohort_size"],
        "prompt_pairs": f"{data['country_prompt_pairs']:,}", "prompt_units": f"{data['country_prompt_units']:,}",
        "all_prompt_pairs": f"{data['prompt_pairs']:,}", "cohort_prompt_pairs": f"{data['cohort_prompt_pairs']:,}",
        "cohort_prompt_units": f"{data['cohort_prompt_units']:,}", "min_active_weeks": study["min_active_weeks"],
        "selection_first": day(study["selection"]["first_week"]), "selection_last": day(study["selection"]["last_week"], 6),
        "first_complete_week": day(data["first_complete_week"]), "last_complete_week": day(data["last_complete_week"], 6),
        "closure_weeks": ", ".join(f"the week of {day(week)}" for week in data["closure_weeks"]) or "none",
        "evaluation_first": day(study["evaluation"]["first_week"]), "evaluation_last": day(study["evaluation"]["last_day"]),
    }


def readme_values(summary: dict) -> dict:
    return {"headline": _headline(summary), "figure": f"exports/{FIGURE}",
            "policy_table": table(_policy_rows(summary, compact=True),
                                  ["Policy", "Modeled cost", "Fill rate", "Mean leftover units"], "lrrr"),
            "sensitivity_sentence": _sensitivity(summary)[1], "bridge_sentence": _bridge_sentence(summary, compact=True),
            "bridge_table": _bridge_table(summary, compact=True)}


def readme_block(summary: dict) -> str:
    """The README's generated results block, markers included."""
    return f"{README_START}\n{render('readme_results.md', readme_values(summary)).strip()}\n{README_END}"


def update_readme(readme: Path, summary: dict) -> bool:
    """Rewrite the README between the markers; returns whether it changed."""
    text = readme.read_text(encoding="utf-8")
    start, end = text.find(README_START), text.find(README_END)
    if start < 0 or end < start:
        raise ValueError(f"{readme} lacks the {README_START} / {README_END} markers")
    updated = text[:start] + readme_block(summary) + text[end + len(README_END):]
    if updated != text:
        readme.write_text(updated, encoding="utf-8")
    return updated != text


# Bundle, manifest and staged publishing ---------------------------------------------------


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(path) -> str:
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name


def source_hashes(config_path) -> dict:
    return {name: sha256(ROOT / name) for name in SOURCES} | {relative(config_path): sha256(config_path)}


def manifest(result: experiment.Result, directory: Path, config_path: Path, input_info: dict) -> dict:
    study, calendar, config = result.study, result.study.calendar, result.config
    artifacts = {}
    for name in ARTIFACTS:
        content = (directory / name).read_bytes()
        artifacts[name] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        if name.endswith(".csv"):
            artifacts[name]["rows"] = content.count(b"\n") - 1
    settings = {key: float(value) if hasattr(value, "denominator") and not isinstance(value, int) else value
                for key, value in vars(config).items() if key not in ("primary", "sensitivities")}
    return _plain({
        "schema_version": SCHEMA_VERSION, "config_file": relative(config_path),
        "config": settings | {"primary": scenario_settings(config.primary),
                              "sensitivities": [scenario_settings(item) for item in config.sensitivities]},
        "input": input_info, "sheets": result.sheets, "sources": source_hashes(config_path),
        "environment": {"python": platform.python_version()} | {name: metadata.version(name) for name in PACKAGES},
        "calendar": {
            "first_week": calendar["week_start"].iloc[0], "last_week": calendar["week_start"].iloc[-1],
            "partial_weeks": list(calendar.loc[~calendar["complete"], "week_start"]),
            "closure_weeks": list(study.closures), "selection": [study.selection[0], study.selection[-1]],
            "evaluation": [study.evaluation[0], study.evaluation[-1]],
        },
        "artifacts": artifacts,
    })


def write_bundle(result: experiment.Result, directory: Path, config_path: Path, input_info: dict) -> dict:
    summary = summarize(result)
    for name, frame in frames(result).items():
        write_csv(frame, directory / name)
    write_cost_difference_figure(weekly_cost(result.primary), NAMES, directory / FIGURE,
                                 baselines=result.config.baselines)
    texts = {"insight_report.md": render("insight_report.md", insight_values(summary)),
             "data_quality.md": render("data_quality.md", quality_values(summary, result.tables)),
             "summary.json": json.dumps(summary, indent=2, ensure_ascii=False) + "\n"}
    for name, text in texts.items():
        (directory / name).write_text(text, encoding="utf-8")
    record = manifest(result, directory, config_path, input_info)
    (directory / MANIFEST).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def check_bundle(directory: Path) -> None:
    """A bundle is complete when every artifact exists and matches the manifest's hash."""
    recorded = json.loads((directory / MANIFEST).read_text(encoding="utf-8")).get("artifacts", {})
    if set(recorded) != set(ARTIFACTS):
        raise RuntimeError("the manifest does not list exactly the published artifacts")
    for name in ARTIFACTS:
        if not (directory / name).is_file() or sha256(directory / name) != recorded[name].get("sha256"):
            raise RuntimeError(f"{name} is missing or does not match the manifest")


def publish(output: Path, write):
    """Write a bundle into a sibling staging folder, check it, then swap it into place; on any
    failure the staging folder is removed and the previous bundle stays as it was."""
    output = Path(output)
    staging, previous = (output.with_name(f"{output.name}.{suffix}") for suffix in ("staging", "previous"))
    if previous.exists() and not output.exists():  # an earlier swap was interrupted
        previous.rename(output)
    for folder in (staging, previous):
        shutil.rmtree(folder, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        value = write(staging)
        check_bundle(staging)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if output.exists():
        output.rename(previous)
    try:
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if previous.exists():
            previous.rename(output)
        raise
    shutil.rmtree(previous, ignore_errors=True)
    return value
