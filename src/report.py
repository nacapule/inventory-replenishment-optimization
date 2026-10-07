"""Turn a study result into the published bundle: CSVs, the figure, the two Markdown
reports, summary.json and run_manifest.json, written to a staging folder and swapped
into place only when complete. The reports' fixed prose lives in templates/; every
number and every sentence that depends on a result's sign is generated here.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import platform
import shutil
import string
from importlib import metadata
from pathlib import Path
from typing import Mapping, Sequence

import matplotlib
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator, FuncFormatter, MaxNLocator

import experiment

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
PHRASES = {  # policy names inside sentences
    "proportional": "proportional allocation", "scaled_fractile": "the scaled critical-fractile rule",
    "optimizer": "the marginal optimizer", "optimizer_unit": "the equal-price optimizer",
    "unconstrained": "the unconstrained newsvendor",
}
README_START, README_END = "<!-- results:start -->", "<!-- results:end -->"


# Formatting -------------------------------------------------------------------------------


def money(value) -> str:
    return "n/a" if value is None or not math.isfinite(value) else f"{'−' if value < 0 else ''}£{abs(value):,.0f}"


def pct(value, digits=1) -> str:
    return "n/a" if value is None or not math.isfinite(value) else f"{value:.{digits}%}".replace("-", "−")


def day(value) -> str:
    return pd.Timestamp(value).strftime("%-d %B %Y")


def change(value) -> str:
    """A relative difference in words: '4.0% higher', '1.3% lower', 'equal'."""
    if value == 0:
        return "equal"
    size = pct(abs(value)) if round(abs(value), 3) else "less than 0.1%"
    return f"{size} {'lower' if value < 0 else 'higher'}"


def signed(value) -> str:
    """A relative difference for tables: '+4.0%', '−1.3%'."""
    return pct(value) if round(abs(value), 3) == 0 else ("+" if value > 0 else "") + pct(value)


def possessive(phrase: str) -> str:
    return phrase + "'s"


def table(rows: Sequence[Sequence], header: Sequence[str], align: str) -> str:
    """A Markdown table; `align` holds 'l' or 'r' per column."""
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---:" if a == "r" else "---" for a in align) + " |"]
    lines += ["| " + " | ".join(str(cell).replace("|", "/") for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def verdict(comparison) -> str:
    low, high = comparison["interval"]["relative"]
    return "lower" if high < 0 else "higher" if low > 0 else "no clear difference"


def describe(comparison, weeks: int, lead: bool = True) -> str:
    """One sign-aware sentence for a paired comparison of total modeled cost; `lead`
    names the policy, otherwise the sentence continues from one that did."""
    baseline = possessive(PHRASES[comparison["baseline"]])
    rel, (low, high) = comparison["relative"], comparison["interval"]["relative"]
    level = int(round(comparison["confidence"] * 100))
    counts = (f"it cost less in {comparison['weeks_won']} of the {weeks} weeks and more in "
              f"{comparison['weeks_lost']}" + (f", the same in {comparison['weeks_tied']}"
                                               if comparison["weeks_tied"] else ""))
    total = f"equal to {baseline}" if rel == 0 else f"{change(rel)} than {baseline}"
    if low == high == 0:
        interval = f"the same in every resample; {counts}"
    elif verdict(comparison) == "no clear difference":
        interval = f"{level}% interval from {change(low)} to {change(high)}; {counts}"
    else:
        ends = sorted([abs(low), abs(high)])
        interval = f"{level}% interval {pct(ends[0])} to {pct(ends[1])} {verdict(comparison)}; {counts}"
    unclear = verdict(comparison) == "no clear difference"
    if lead:
        subject = possessive(PHRASES[comparison["policy"]])
        return (f"{subject[0].upper()}{subject[1:]} modeled cost was {total}"
                + (", with no clear difference" if unclear else "") + f" ({interval}).")
    total = "equal in total" if rel == 0 else change(rel) + (" in total" if unclear else "")
    if unclear:
        return f"Against {PHRASES[comparison['baseline']]}, there was no clear difference: {total} ({interval})."
    return f"Against {PHRASES[comparison['baseline']]}, it was {total} ({interval})."


# Summary ----------------------------------------------------------------------------------


def _plain(value):
    """JSON-ready values: dates as ISO days, NaN as null, floats rounded to 6 places."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        stamp = pd.Timestamp(value)
        return stamp.strftime("%Y-%m-%d") if stamp == stamp.normalize() else stamp.isoformat()
    if isinstance(value, (np.integer, bool, np.bool_)):
        return value.item() if hasattr(value, "item") else value
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(value) else round(float(value), 6)
    return value


def _comparisons(result_comparisons, policy, block, confidence):
    out = []
    for comparison in result_comparisons:
        entry = {key: comparison[key] for key in ("baseline", "policy_cost", "baseline_cost", "difference",
                                                  "relative", "weeks_won", "weeks_lost", "weeks_tied")}
        entry.update(policy=policy, confidence=float(confidence), block_weeks=block,
                     interval=comparison["intervals"][block])
        entry["checks"] = [{"block_weeks": other, **comparison["intervals"][other]}
                           for other in comparison["intervals"] if other != block]
        entry["verdict"] = verdict(entry)
        out.append(entry)
    return out


def _policies(scenario_result) -> list:
    rows = []
    for policy, run in scenario_result.runs.items():
        row = {"id": policy, "name": experiment.POLICIES[policy], "reference": policy in experiment.REFERENCES}
        row.update(experiment.policy_summary(run, scenario_result.capacity))
        rows.append(row)
    return rows


def best_within_capacity(policies) -> str:
    feasible = [row for row in policies if not row["reference"] and row["within_capacity"]]
    return min(feasible, key=lambda row: row["total_cost"])["id"]


def scenario_settings(scenario: experiment.Scenario) -> dict:
    return {"id": scenario.id, "label": scenario.label, "window": scenario.window,
            "closure_weeks": scenario.closures, "capacity_factor": float(scenario.capacity_factor),
            "holding_rate": float(scenario.holding_rate), "shortage_rate": float(scenario.shortage_rate),
            "critical_ratio": float(scenario.critical_ratio),
            "bulk_cap_quantile": None if scenario.bulk_cap is None else float(scenario.bulk_cap),
            **{key: value for key, value in vars(scenario.rules).items()}}


def summarize(result: experiment.Result) -> dict:
    """The one summary every report and the README block are rendered from."""
    config, study, primary = result.config, result.study, result.primary
    weeks = study.evaluation
    policies = _policies(primary)
    sensitivity = []
    for scenario_result in result.scenarios:
        rows = _policies(scenario_result)
        sensitivity.append({
            **scenario_settings(scenario_result.scenario), "capacity_units": scenario_result.capacity,
            "costs": {row["id"]: row["total_cost"] for row in rows}, "best_within_capacity": best_within_capacity(rows),
            "comparisons": _comparisons(scenario_result.comparisons, config.policy, config.block_weeks,
                                        config.confidence),
        })
    tables = result.tables
    pairs = tables["pairs"]
    local = pairs.loc[pairs["sale_country"].eq(config.country)]
    largest = dict(result.largest)
    return _plain({
        "schema_version": SCHEMA_VERSION,
        "study": {
            "country": config.country, "skus": list(study.cohort), "cohort_size": len(study.cohort),
            "capacity_units": primary.capacity, "mean_weekly_units": float(study.mean_units),
            "capacity_factor": float(config.primary.capacity_factor),
            "selection": {"first_week": study.selection[0], "last_week": study.selection[-1],
                          "weeks": len(study.selection),
                          "open_weeks": len(study.selection.difference(study.closures))},
            "evaluation": {"first_week": weeks[0], "last_day": weeks[-1] + pd.Timedelta(6, "D"),
                           "weeks": len(weeks), "closure_weeks": list(weeks.intersection(study.closures))},
            "holding_rate": float(config.primary.holding_rate), "shortage_rate": float(config.primary.shortage_rate),
            "critical_ratio": float(config.primary.critical_ratio), "window": config.primary.window,
            "window_label": experiment.WINDOWS[config.primary.window][0], "min_active_weeks": config.min_active_weeks,
        },
        "settings": {"reversal_hours": config.reversal_hours, "block_weeks": config.block_weeks,
                     "resamples": config.resamples, "bridge_sheet": config.bridge_sheet,
                     "bridge_holdout_weeks": config.bridge_holdout_weeks,
                     "bridge_min_active_weeks": config.bridge_min_active_weeks,
                     "bridge_capacity_share": float(config.bridge_capacity_share)},
        "policies": policies,
        "best_within_capacity": best_within_capacity(policies),
        "comparisons": _comparisons(primary.comparisons, config.policy, config.block_weeks, config.confidence),
        "quarters": experiment.quarters(primary).to_dict("records"),
        "sku_contributions": experiment.sku_contributions(primary).to_dict("records"),
        "sensitivity": sensitivity,
        "bridge": result.bridge.drop(columns=["cohort"]).to_dict("records"),
        "forecasts": result.forecasts.to_dict("records"),
        "largest_week": largest,
        "data": {
            "sheets": result.sheets, "country_stages": tables["stages"].to_dict("records"),
            "prompt_pairs": len(pairs), "country_prompt_pairs": len(local), "country_prompt_units": int(local["units"].sum()),
            "cohort_prompt_pairs": int(local["sku"].isin(study.cohort).sum()),
            "cohort_prompt_units": int(local.loc[local["sku"].isin(study.cohort), "units"].sum()),
            "largest_prompt_pairs": local.nlargest(5, "units")[["sku", "units", "sale_invoice", "credit_invoice",
                                                            "sale_time", "lag_minutes"]].to_dict("records"),
            "closure_weeks": list(study.closures), "first_complete_week": study.complete[0],
            "last_complete_week": study.complete[-1],
        },
    })


def console_line(summary: dict, output) -> str:
    """The run's one-line console report: the best policy within capacity, the reference apart."""
    names = {row["id"]: row for row in summary["policies"]}
    best = names[summary["best_within_capacity"]]
    references = [row for row in summary["policies"] if row["reference"]]
    line = (f"wrote {output} | {summary['study']['cohort_size']} SKUs | capacity {summary['study']['capacity_units']:,} "
            f"units | lowest modeled cost within capacity: {best['name']} ({money(best['total_cost'])})")
    for row in references:
        line += f" | reference without the limit: {row['name']} ({money(row['total_cost'])})"
    return line


# Tables for the CSVs ----------------------------------------------------------------------


def _dates(frame: pd.DataFrame) -> pd.DataFrame:
    """Datetime columns as text: whole days as YYYY-MM-DD, other times to the second."""
    frame = frame.copy()
    for column in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            values = frame[column]
            whole = values.dropna().eq(values.dropna().dt.normalize()).all()
            frame[column] = values.dt.strftime("%Y-%m-%d" if whole else "%Y-%m-%d %H:%M:%S")
    return frame


def frames(result: experiment.Result) -> dict:
    """Every published CSV as a frame, keyed by file name."""
    config, primary = result.config, result.primary
    comparison = pd.DataFrame([{
        "policy": row["name"], "allocated_units": row["allocated_units"], "fill_rate": row["fill_rate"],
        "stockout_rate": row["stockout_rate"], "holding_cost": row["holding_cost"],
        "shortage_cost": row["shortage_cost"], "total_cost": row["total_cost"], "policy_id": row["id"],
        "within_capacity": row["within_capacity"], "capacity_units": primary.capacity,
        "ordered_units": row["ordered_units"], "leftover_units": row["leftover_units"], "reference": row["reference"],
    } for row in _policies(primary)])
    weekly = []
    for policy, run in primary.runs.items():
        records = pd.DataFrame(run.records())
        records.insert(0, "policy_id", policy)
        records["week"] = primary.weeks[records["week"].to_numpy()]
        records.insert(3, "price", primary.prices.ravel())
        weekly.append(records.rename(columns={"week": "week_start"}))
    sensitivity = []
    for scenario_result in result.scenarios:
        row = scenario_settings(scenario_result.scenario)
        row["capacity_units"] = scenario_result.capacity
        rows = _policies(scenario_result)
        row.update({f"{policy['id']}_cost": policy["total_cost"] for policy in rows})
        for item in scenario_result.comparisons:
            name = f"{config.policy}_vs_{item['baseline']}"
            low, high = item["intervals"][config.block_weeks]["relative"]
            row.update({name: item["relative"], f"{name}_low": low, f"{name}_high": high,
                        f"{name}_weeks_won": item["weeks_won"], f"{name}_weeks_lost": item["weeks_lost"]})
        row["best_within_capacity"] = best_within_capacity(rows)
        sensitivity.append(row)
    tables = result.tables
    return {
        "policy_comparison.csv": comparison,
        "sku_decisions.csv": result.decisions,
        "forecast_metrics.csv": result.forecasts,
        "weekly_results.csv": pd.concat(weekly, ignore_index=True),
        "sensitivity.csv": pd.DataFrame(sensitivity).rename(columns={"id": "scenario"}),
        "published_bridge.csv": result.bridge,
        "reconciliation.csv": tables["reconciliation"],
        "reversal_pairs.csv": tables["pairs"],
        "weekly_sales.csv": tables["weekly_sales"],
    }


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    _dates(frame).to_csv(path, index=False, lineterminator="\n")


# The figure -------------------------------------------------------------------------------


def weekly_cost(scenario_result) -> pd.DataFrame:
    frame = pd.DataFrame({policy: run.cost.sum(axis=1) for policy, run in scenario_result.runs.items()},
                         index=scenario_result.weeks)
    frame.index.name = "week_start"
    return frame


SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")

# Every setting the drawing depends on, so a user's matplotlibrc cannot change the file.
FIGURE_RC = {
    "svg.hashsalt": "inventory-replenishment",
    "svg.fonttype": "none",
    "svg.image_inline": True,
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Verdana", "Arial", "Helvetica"],
    "font.size": 10.0,
    "font.weight": "normal",
    "text.color": INK,
    "text.parse_math": False,
    "text.hinting": "default",
    "text.kerning_factor": None,
    "figure.dpi": 100.0,
    "savefig.dpi": 100.0,
    "figure.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "savefig.edgecolor": SURFACE,
    "savefig.bbox": None,
    "savefig.pad_inches": 0.1,
    "figure.autolayout": False,
    "figure.constrained_layout.use": False,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": INK_MUTED,
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.left": False,
    "axes.spines.bottom": True,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "axes.axisbelow": True,
    "axes.unicode_minus": True,
    "axes.labelcolor": INK_SECONDARY,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "grid.linestyle": "-",
    "grid.alpha": 1.0,
    "xtick.color": INK_MUTED,
    "ytick.color": INK_MUTED,
    "xtick.labelcolor": INK_SECONDARY,
    "ytick.labelcolor": INK_SECONDARY,
    "xtick.labelsize": 9.5,
    "ytick.labelsize": 9.5,
    "xtick.direction": "out",
    "xtick.major.size": 4.0,
    "xtick.major.width": 0.8,
    "xtick.major.pad": 4.0,
    "ytick.left": False,
    "ytick.major.size": 0.0,
    "ytick.major.pad": 6.0,
    "lines.linewidth": 1.6,
    "lines.solid_capstyle": "round",
    "lines.solid_joinstyle": "round",
    "lines.antialiased": True,
    "path.simplify": True,
    "path.simplify_threshold": 1.0 / 9.0,
    "path.snap": True,
    "timezone": "UTC",
}


def cost_difference(weekly_cost: pd.DataFrame, reference: str = "optimizer",
                    baselines: Sequence[str] = ("scaled_fractile", "proportional")) -> pd.DataFrame:
    """Cumulative (reference - baseline) cost per week; index week_start, one column per baseline id."""
    weekly = {baseline: weekly_cost[reference] - weekly_cost[baseline] for baseline in baselines}
    return pd.DataFrame(weekly, index=weekly_cost.index).cumsum()


def _pounds(value: float, decimals: int = 0) -> str:
    """Signed GBP amount: '+£1,234', '−£56', '£0'."""
    if round(value, decimals) == 0:
        return f"£{0:,.{decimals}f}"
    sign = "+" if value > 0 else "−"
    return f"{sign}£{abs(value):,.{decimals}f}"


def _date_label(value: float, monthly: bool, show_year: bool) -> str:
    day = mdates.num2date(value)
    if not monthly:
        return f"{day.day} {day:%b}"
    return f"{day:%b}\n{day.year}" if show_year else f"{day:%b}"


def _build_figure(cumulative: pd.DataFrame, names: Mapping[str, str], reference: str) -> Figure:
    if len(cumulative.columns) > len(SERIES):
        raise ValueError(f"at most {len(SERIES)} baselines can be plotted")
    weeks = cumulative.index
    x = mdates.date2num(weeks.to_pydatetime())
    count = len(weeks)

    fig = Figure(figsize=(9.6, 5.0))
    ax = fig.add_axes((0.085, 0.13, 0.64, 0.65))

    # Fixed limits and ticks, so the layout below can be computed before drawing.
    low = min(0.0, float(np.nanmin(cumulative.to_numpy())))
    high = max(0.0, float(np.nanmax(cumulative.to_numpy())))
    if high - low == 0:
        low, high = -1.0, 1.0
    y_ticks = MaxNLocator(nbins=6, steps=[1, 2, 2.5, 5, 10]).tick_values(low, high)
    y_ticks = y_ticks[(y_ticks >= low - 1e-9) & (y_ticks <= high + 1e-9)]
    step = float(y_ticks[1] - y_ticks[0]) if len(y_ticks) > 1 else high - low
    decimals = 0 if step >= 1 else 2
    pad = 0.08 * (high - low)
    ax.set_ylim(low - pad, high + pad)
    ax.yaxis.set_major_locator(FixedLocator(y_ticks))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: _pounds(v, decimals)))

    margin = datetime.timedelta(hours=60)
    ax.set_xlim(mdates.date2num([weeks[0] - margin, weeks[-1] + margin]))
    span = (weeks[-1] - weeks[0]).days
    monthly = span > 120
    if monthly:
        ticks = pd.date_range(weeks[0].replace(day=1), weeks[-1] + margin, freq="MS")
        ticks = ticks[ticks >= weeks[0] - margin]
    else:
        ticks = weeks[:: 2 if span > 42 else 1]
    x_ticks = mdates.date2num(ticks.to_pydatetime())
    year_ticks = {float(t) for t, day in zip(x_ticks, ticks) if t == x_ticks[0] or day.month == 1}
    ax.xaxis.set_major_locator(FixedLocator(x_ticks))
    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda v, _pos: _date_label(v, monthly, v in year_ticks)))

    ax.axhline(0, color=INK_MUTED, linewidth=1.0, zorder=1)

    # End labels: baseline name over the final amount, pushed apart when they would collide.
    to_px = ax.transData.transform
    to_data = ax.transData.inverted().transform
    finals = [(column, float(cumulative[column].iloc[-1])) for column in cumulative.columns]
    label_px = sorted(((to_px((x[-1], y))[1], i) for i, (_, y) in enumerate(finals)), reverse=True)
    placed = {}
    previous = None
    for y_px, i in label_px:
        if previous is not None and previous - y_px < 30:
            y_px = previous - 30
        placed[i] = y_px
        previous = y_px
    shift = np.mean([to_px((x[-1], y))[1] for _, y in finals]) - np.mean(list(placed.values()))
    anchor_x = to_data((to_px((x[-1], 0))[0] + 14, 0))[0]

    for i, (column, final) in enumerate(finals):
        color = SERIES[i]
        ax.plot(x, cumulative[column].to_numpy(), color=color, zorder=3)
        ax.plot([x[-1]], [final], marker="o", markersize=6.5, color=color,
                markeredgecolor=SURFACE, markeredgewidth=1.5, linestyle="none",
                clip_on=False, zorder=5)
        label_y = to_data((0, placed[i] + shift))[1]
        if abs(placed[i] + shift - to_px((x[-1], final))[1]) > 2:
            ax.plot([x[-1], anchor_x], [final, label_y], color=INK_MUTED, linewidth=0.7,
                    clip_on=False, zorder=2)
        ax.annotate(names[column], (anchor_x, label_y), xytext=(2, 1), textcoords="offset points",
                    ha="left", va="bottom", fontsize=9.5, color=INK_SECONDARY, annotation_clip=False)
        ax.annotate(_pounds(final, decimals), (anchor_x, label_y), xytext=(2, -1),
                    textcoords="offset points", ha="left", va="top", fontsize=10.5,
                    fontweight="bold", color=INK, annotation_clip=False)

    first, last = weeks[0], weeks[-1] + pd.Timedelta(6, "D")
    weeks_text = f"{count} week" if count == 1 else f"{count} weeks"
    subject = names[reference][:1].lower() + names[reference][1:]
    fig.text(0.085, 0.955, f"Cumulative difference in modeled cost: {names[reference]} minus each baseline",
             fontsize=13, fontweight="bold", color=INK, ha="left", va="top")
    fig.text(0.085, 0.895,
             f"Weekly differences summed from {first.day} {first:%b %Y} to {last.day} {last:%b %Y} "
             f"({weeks_text}).\nAbove zero, the {subject} has cost more than that baseline "
             f"so far; below zero, less.",
             fontsize=10, color=INK_SECONDARY, ha="left", va="top", linespacing=1.5)
    return fig


def write_cost_difference_figure(weekly_cost: pd.DataFrame, names: Mapping[str, str], path: Path,
                                 reference: str = "optimizer",
                                 baselines: Sequence[str] = ("scaled_fractile", "proportional")) -> None:
    """Write the SVG to `path`."""
    cumulative = cost_difference(weekly_cost, reference, baselines)
    with matplotlib.rc_context(FIGURE_RC):
        fig = _build_figure(cumulative, names, reference)
        fig.savefig(path, format="svg", metadata={"Date": None, "Creator": None})


# Reports ----------------------------------------------------------------------------------


def render(name: str, values: Mapping[str, object]) -> str:
    return string.Template((TEMPLATES / name).read_text(encoding="utf-8")).substitute(values)


def _policy_rows(summary, compact=False):
    rows = []
    for row in summary["policies"]:
        name = row["name"] + (" (reference, ignores the limit)" if row["reference"] else "")
        if compact:
            rows.append([name, money(row["total_cost"]), pct(row["fill_rate"]), f"{row['leftover_units']:,.0f}"])
        else:
            rows.append([name, "yes" if row["within_capacity"] else "no", money(row["total_cost"]),
                         money(row["holding_cost"]), money(row["shortage_cost"]), pct(row["fill_rate"]),
                         pct(row["stockout_rate"]), f"{row['allocated_units']:,.0f}",
                         f"{row['leftover_units']:,.0f}", f"{row['ordered_units']:,}"])
    return rows


def _interval(values) -> str:
    low, high = values
    return f"{signed(low)} to {signed(high)}"


def _headline(summary) -> str:
    study = summary["study"]
    weeks = study["evaluation"]["weeks"]
    sentences = [describe(comparison, weeks, lead=index == 0)
                 for index, comparison in enumerate(summary["comparisons"])]
    sentences[0] = (f"Over the {weeks} evaluation weeks, {day(study['evaluation']['first_week'])} to "
                    f"{day(study['evaluation']['last_day'])}, " + sentences[0][0].lower() + sentences[0][1:])
    best = next(row for row in summary["policies"] if row["id"] == summary["best_within_capacity"])
    text = (f"The lowest modeled cost within the limit was {possessive(PHRASES[best['id']])} "
            f"({money(best['total_cost'])})")
    for row in summary["policies"]:
        if row["reference"]:
            text += f"; {PHRASES[row['id']]}, which ignores the limit, came to {money(row['total_cost'])}"
    return " ".join(sentences + [text + "."])


def _bridge_sentence(summary) -> str:
    rows = summary["bridge"]
    first, last = rows[0], rows[-1]
    text = (f"Rerun as originally designed, {PHRASES['optimizer']}'s modeled cost was "
            f"{change(first['optimizer_vs_proportional'])} than {possessive(PHRASES['proportional'])}.")
    if len(rows) > 1:
        text += (f" With all {len(rows) - 1} corrections applied, it was {change(last['optimizer_vs_proportional'])} "
                 f"than {possessive(PHRASES['proportional'])} and {change(last['optimizer_vs_scaled_fractile'])} "
                 f"than {possessive(PHRASES['scaled_fractile'])}.")
    return text


def _bridge_table(summary, compact=False) -> str:
    rows = []
    for row in summary["bridge"]:
        changes = " ".join(filter(None, [f"+{row['skus_added']}" if row["skus_added"] else "",
                                         f"−{row['skus_removed']}" if row["skus_removed"] else ""]))
        cells = [row["label"], f"{row['train_weeks']} / {row['holdout_weeks']}", f"{row['capacity_units']:,}"]
        cells += [] if compact else [changes.replace(" ", ", ") or "none"]
        cells += [money(row["optimizer_cost"]), money(row["scaled_fractile_cost"]), money(row["proportional_cost"]),
                  change(row["optimizer_vs_proportional"])]
        rows.append(cells)
    header = ["Step", "Training / holdout weeks", "Capacity"] + ([] if compact else ["Cohort changes"])
    header += ["Marginal optimizer", "Scaled critical-fractile", "Proportional", "Optimizer vs proportional"]
    return table(rows, header, "lrr" + ("" if compact else "l") + "rrrr")


def _sensitivity(summary):
    rows, counts = [], {}
    for index, entry in enumerate(summary["sensitivity"]):
        cells = [entry["label"], f"{entry['capacity_units']:,}"]
        for comparison in entry["comparisons"]:
            low, high = comparison["interval"]["relative"]
            cells.append(f"{signed(comparison['relative'])} ({signed(low)} to {signed(high)})")
            if index:
                key = (comparison["baseline"], comparison["verdict"])
                counts[key] = counts.get(key, 0) + 1
        cells.append(experiment.POLICIES[entry["best_within_capacity"]])
        rows.append(cells)
    header = ["Scenario", "Capacity"] + [f"Optimizer vs {experiment.POLICIES[c['baseline']].lower()}"
                                         for c in summary["comparisons"]] + ["Lowest cost within the limit"]
    others = len(summary["sensitivity"]) - 1
    parts = []
    for number, comparison in enumerate(summary["comparisons"]):
        lower, higher, unclear = (counts.get((comparison["baseline"], kind), 0)
                                  for kind in ("lower", "higher", "no clear difference"))
        name = PHRASES[comparison["baseline"]]
        parts.append((f"clearly lower than {possessive(name)} in {lower}" if number == 0 else
                      f"against {name}, clearly lower in {lower}")
                     + f", clearly higher in {higher} and not clearly different in {unclear}")
    policy = PHRASES[summary["comparisons"][0]["policy"]]
    sentence = (f"Across the {others} sensitivities, {possessive(policy)} modeled cost was "
                + "; ".join(parts) + ".") if others else ""
    return table(rows, header, "lr" + "r" * len(summary["comparisons"]) + "l"), sentence


def _largest(summary) -> str:
    item = summary["largest_week"]
    text = (f"The largest single week for a cohort product, relative to its typical selling week, was "
            f"{item['units']:,} units of {item['sku']} ({item['description']}) in the week of {day(item['week'])}, "
            f"{item['ratio']:,.0f} times its median selling week of {item['typical_units']:,.0f} units. Its largest "
            f"line was invoice {item['invoice']} ({item['line_units']:,} units, "
            f"{'no customer recorded' if item['anonymous'] else 'a known customer'}).")
    credit = item["credit"]
    if credit:
        text += (f" That line was later matched by credit {credit['invoice']}, {credit['lag_days']:,.1f} days after "
                 f"the sale; credits later than a day stay in the credit ledger and are not removed from sales.")
    else:
        text += " No credit in the source matches that line."
    return text


def insight_values(summary: dict) -> dict:
    study, weeks = summary["study"], summary["study"]["evaluation"]["weeks"]
    comparison_rows = []
    for item in summary["comparisons"]:
        checks = "; ".join(f"{check['block_weeks']}-week blocks: {_interval(check['relative'])}"
                           for check in item["checks"])
        comparison_rows.append([
            f"Optimizer vs {experiment.POLICIES[item['baseline']].lower()}", money(item["policy_cost"]),
            money(item["baseline_cost"]), money(item["difference"]), signed(item["relative"]),
            _interval(item["interval"]["relative"]), checks or "none",
            f"{item['weeks_won']} / {item['weeks_lost']}" + (f" / {item['weeks_tied']}" if item["weeks_tied"] else "")])
    feasible = [row["id"] for row in summary["policies"] if not row["reference"]]
    quarter_rows = [[f"{q['quarter']} ({day(q['first_week'])} to {day(pd.Timestamp(q['last_week']) + pd.Timedelta(6, 'D'))})"]
                    + [money(q[policy]) for policy in feasible]
                    + [money(q[summary["comparisons"][0]["policy"]] - q[c["baseline"]]) for c in summary["comparisons"]]
                    for q in summary["quarters"]]
    policy = summary["comparisons"][0]["policy"]
    skus = sorted(summary["sku_contributions"], key=lambda row: -(row[f"{policy}_cost"]
                                                                  - row[f"{summary['comparisons'][0]['baseline']}_cost"]))
    sku_rows = [[row["sku"], f"{row['sales_units']:,}"] + [money(row[f"{p}_cost"]) for p in feasible]
                + [money(row[f"{policy}_cost"] - row[f"{c['baseline']}_cost"]) for c in summary["comparisons"]]
                for row in skus]
    differences = [f"Optimizer minus {experiment.POLICIES[c['baseline']].lower()}" for c in summary["comparisons"]]
    sensitivity_table, sensitivity_sentence = _sensitivity(summary)
    forecast_rows = [[row["method"], pct(row["wape"]), pct(row["bias"]), f"{row['mae']:,.1f}",
                      f"{row['pinball_loss']:,.1f}"] for row in summary["forecasts"]]
    level = int(round(summary["comparisons"][0]["confidence"] * 100))
    return {
        "headline": _headline(summary), "country": study["country"], "cohort_size": study["cohort_size"],
        "capacity": f"{study['capacity_units']:,}",
        "capacity_basis": ("" if study["capacity_factor"] == 1 else f"{study['capacity_factor']:g} times ")
        + f"the cohort's mean weekly sales ({study['mean_weekly_units']:,.1f} units)",
        "selection_weeks": study["selection"]["weeks"], "open_selection_weeks": study["selection"]["open_weeks"],
        "selection_first": day(study["selection"]["first_week"]),
        "selection_last": day(pd.Timestamp(study["selection"]["last_week"]) + pd.Timedelta(6, "D")),
        "evaluation_first": day(study["evaluation"]["first_week"]), "evaluation_last": day(study["evaluation"]["last_day"]),
        "evaluation_weeks": weeks, "holding_pct": pct(study["holding_rate"]), "shortage_pct": pct(study["shortage_rate"]),
        "critical_ratio": f"{study['critical_ratio']:.4f}", "window_label": study["window_label"].lower(),
        "min_active_weeks": study["min_active_weeks"], "confidence": f"{level}%",
        "block_weeks": summary["comparisons"][0]["block_weeks"],
        "policy_table": table(_policy_rows(summary), ["Policy", "Within the limit", "Modeled cost", "Holding",
                                                      "Shortage", "Fill rate", "SKU-weeks short", "Mean start stock",
                                                      "Mean leftover", "Units ordered"], "llrrrrrrrr"),
        "comparison_table": table(comparison_rows, ["Comparison", "Optimizer", "Baseline", "Difference", "Relative",
                                                    f"{level}% interval", "Interval checks",
                                                    "Weeks lower / higher"], "lrrrrrll"),
        "quarter_table": table(quarter_rows, ["Quarter"] + [experiment.POLICIES[p] for p in feasible] + differences,
                               "l" + "r" * (len(feasible) + len(differences))),
        "sku_table": table(sku_rows, ["SKU", "Sales units"] + [experiment.POLICIES[p] for p in feasible] + differences,
                           "lr" + "r" * (len(feasible) + len(differences))),
        "sensitivity_table": sensitivity_table, "sensitivity_sentence": sensitivity_sentence,
        "bridge_sentence": _bridge_sentence(summary), "bridge_table": _bridge_table(summary),
        "forecast_table": table(forecast_rows, ["History window", "WAPE", "Bias", "MAE (units)",
                                                "Pinball loss (units)"], "lrrrr"),
        "largest_week": _largest(summary), "figure": FIGURE,
        "reversal_hours": summary["settings"]["reversal_hours"], "resamples": f"{summary['settings']['resamples']:,}",
        "bridge_sheet": summary["settings"]["bridge_sheet"],
        "bridge_holdout_weeks": summary["settings"]["bridge_holdout_weeks"],
        "bridge_min_active_weeks": summary["settings"]["bridge_min_active_weeks"],
        "bridge_share": pct(summary["settings"]["bridge_capacity_share"], 0),
        "decision_week": day(pd.Timestamp(summary["study"]["evaluation"]["last_day"]) + pd.Timedelta(1, "D")),
    }


def _cell(column: str, value) -> str:
    """A data-report cell: counts with separators, values in pounds, shares in percent."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if column in ("value", "revenue"):
        return f"£{value:,.2f}".replace("£-", "−£")
    if column.endswith("share"):
        return pct(value)
    if column.endswith(("_seen", "_time")):
        return str(value).replace("T", " ")[:16] if column.endswith("_time") else day(value)
    if isinstance(value, (int, np.integer)) or (isinstance(value, float) and value.is_integer()):
        return f"{int(value):,}".replace("-", "−")
    return f"{value:,.0f}" if isinstance(value, float) else str(value)


def _frame_table(frame, columns: dict) -> str:
    """A Markdown table of `frame`; `columns` maps each column to its header (text left, numbers right)."""
    rows = [[_cell(column, record[column]) for column in columns] for record in frame.to_dict("records")]
    align = "".join("r" if pd.api.types.is_numeric_dtype(frame[column]) else "l" for column in columns)
    return table(rows, list(columns.values()), align) if rows else "None."


def quality_values(summary: dict, tables: dict) -> dict:
    data_, study = summary["data"], summary["study"]
    sheets, lines = data_["sheets"], {"rows": "Lines", "units": "Units"}
    return {
        "sheet_rows": ", ".join(f"{name}: {rows:,}" for name, rows in sheets["rows"].items()),
        "overlap_rows": f"{sheets['overlap_rows']:,}", "combined_rows": f"{sheets['combined_rows']:,}",
        "source_rows": f"{sum(sheets['rows'].values()):,}", "country": study["country"],
        "reversal_hours": summary["settings"]["reversal_hours"], "cohort_size": study["cohort_size"],
        "prompt_pairs": f"{data_['country_prompt_pairs']:,}", "prompt_units": f"{data_['country_prompt_units']:,}",
        "all_prompt_pairs": f"{data_['prompt_pairs']:,}", "cohort_prompt_pairs": f"{data_['cohort_prompt_pairs']:,}",
        "cohort_prompt_units": f"{data_['cohort_prompt_units']:,}",
        "selection_last": day(pd.Timestamp(study["selection"]["last_week"]) + pd.Timedelta(6, "D")),
        "min_active_weeks": study["min_active_weeks"],
        "selection_table": _frame_table(tables["selection"], {
            "sku": "SKU", "description": "Description", "active_weeks": "Weeks sold", "units": "Units",
            "revenue": "Revenue"}),
        "reconciliation_table": _frame_table(tables["reconciliation"], {
            "sheet": "Sheet", "role": "Role", "rows": "Rows", "units": "Units", "value": "Value"}),
        "stage_table": _frame_table(tables["stages"], {"stage": "Stage", **lines, "value": "Value"}),
        "largest_pairs_table": _frame_table(pd.DataFrame(data_["largest_prompt_pairs"]), {
            "sku": "SKU", "units": "Units", "sale_invoice": "Sale", "credit_invoice": "Credit",
            "sale_time": "Sale time", "lag_minutes": "Minutes later"}),
        "credit_table": _frame_table(tables["credits"], {
            "status": "Status", "lag_bucket": "Lag", "credits": "Credits", "units": "Units", "value": "Value",
            "reinvoice_candidates": "Re-invoiced", "reinvoiced_units": "Re-invoiced units"}),
        "registry_table": _frame_table(tables["registry"], {
            "code": "Code", "code_class": "Class", "code_action": "Action", **lines, "value": "Value",
            "description": "Description"}),
        "unusual_table": _frame_table(tables["unusual"], {"sku": "Code", **lines, "description": "Description"}),
        "alias_table": _frame_table(tables["aliases"], {"sku": "SKU", "stock_code": "Written as", **lines}),
        "drift_table": _frame_table(tables["drift"], {"sku": "SKU", "description": "Description", **lines,
                                                      "first_seen": "First seen", "last_seen": "Last seen"}),
        "concentration_table": _frame_table(tables["concentration"], {
            "sku": "SKU", "units": "Units", "customers": "Customers", "anonymous_share": "Anonymous",
            "top_customer_share": "Top customer", "top_invoice_share": "Top invoice"}),
        "repeated_table": _frame_table(tables["repeated"], {
            "sheet": "Sheet", "rows": "Rows", "repeated_rows": "Repeated rows",
            "repeated_units": "Units on repeated rows"}),
        "first_complete_week": day(data_["first_complete_week"]),
        "last_complete_week": day(pd.Timestamp(data_["last_complete_week"]) + pd.Timedelta(6, "D")),
        "closure_weeks": ", ".join(f"the week of {day(week)}" for week in data_["closure_weeks"]) or "none",
        "selection_first": day(study["selection"]["first_week"]),
        "evaluation_first": day(study["evaluation"]["first_week"]),
        "evaluation_last": day(study["evaluation"]["last_day"]),
    }


def readme_values(summary: dict) -> dict:
    return {
        "headline": _headline(summary),
        "policy_table": table(_policy_rows(summary, compact=True),
                              ["Policy", "Modeled cost", "Fill rate", "Mean leftover units"], "lrrr"),
        "figure": f"exports/{FIGURE}", "sensitivity_sentence": _sensitivity(summary)[1],
        "bridge_sentence": _bridge_sentence(summary), "bridge_table": _bridge_table(summary, compact=True),
    }


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
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def resolved(config: experiment.Config) -> dict:
    values = {key: value for key, value in vars(config).items() if key not in ("primary", "sensitivities")}
    values["primary"] = scenario_settings(config.primary)
    values["sensitivities"] = [scenario_settings(scenario) for scenario in config.sensitivities]
    return _plain({key: float(value) if hasattr(value, "denominator") and not isinstance(value, int) else value
                   for key, value in values.items()})


def source_hashes(root: Path = ROOT, config_path: Path | None = None) -> dict:
    hashes = {name: sha256(root / name) for name in SOURCES}
    if config_path is not None:
        hashes[relative(config_path)] = sha256(Path(config_path))
    return hashes


def relative(path) -> str:
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name


def manifest(result: experiment.Result, directory: Path, config_path: Path, input_info: dict) -> dict:
    study = result.study
    calendar = study.calendar
    artifacts = {}
    for name in ARTIFACTS:
        path = directory / name
        entry = {"sha256": sha256(path), "bytes": path.stat().st_size}
        if name.endswith(".csv"):
            with open(path, encoding="utf-8") as handle:
                entry["rows"] = sum(1 for _ in handle) - 1
        artifacts[name] = entry
    return _plain({
        "schema_version": SCHEMA_VERSION, "config_file": relative(config_path), "config": resolved(result.config),
        "input": input_info, "sheets": result.sheets, "sources": source_hashes(ROOT, config_path),
        "environment": {"python": platform.python_version(), **{name: metadata.version(name) for name in PACKAGES}},
        "calendar": {
            "first_week": calendar["week_start"].iloc[0], "last_week": calendar["week_start"].iloc[-1],
            "partial_weeks": list(calendar.loc[~calendar["complete"], "week_start"]),
            "closure_weeks": list(study.closures),
            "selection": [study.selection[0], study.selection[-1]],
            "evaluation": [study.evaluation[0], study.evaluation[-1]],
        },
        "artifacts": artifacts,
    })


def write_bundle(result: experiment.Result, directory: Path, config_path: Path, input_info: dict) -> dict:
    summary = summarize(result)
    for name, frame in frames(result).items():
        write_csv(frame, directory / name)
    write_cost_difference_figure(weekly_cost(result.primary), experiment.POLICIES, directory / FIGURE,
                                 result.config.policy, result.config.baselines)
    (directory / "insight_report.md").write_text(render("insight_report.md", insight_values(summary)), encoding="utf-8")
    (directory / "data_quality.md").write_text(render("data_quality.md", quality_values(summary, result.tables)),
                                               encoding="utf-8")
    (directory / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    record = manifest(result, directory, config_path, input_info)
    (directory / MANIFEST).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def check_bundle(directory: Path) -> None:
    """A bundle is complete when every artifact exists and matches the manifest's hash."""
    record = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    for name in ARTIFACTS:
        if not (directory / name).is_file() or sha256(directory / name) != record["artifacts"][name]["sha256"]:
            raise RuntimeError(f"{name} is missing or does not match the manifest")


def publish(output: Path, write) -> object:
    """Write a bundle into a sibling staging folder, check it, then swap it into place.

    On any failure the staging folder is removed and the previous bundle stays as it was.
    """
    output = Path(output)
    staging, previous = output.with_name(output.name + ".staging"), output.with_name(output.name + ".previous")
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
    staging.rename(output)
    shutil.rmtree(previous, ignore_errors=True)
    return value
