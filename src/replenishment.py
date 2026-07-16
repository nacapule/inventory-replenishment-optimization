#!/usr/bin/env python3
"""Backtest forecasts and allocate constrained weekly inventory.

The optimization problem is a separable, discrete newsvendor model:

    minimize  sum_i h_i E[(q_i - D_i)+] + p_i E[(D_i - q_i)+]
    subject to sum_i q_i <= capacity, q_i non-negative integers.

For empirical demand distributions, each SKU's expected cost is discrete convex.
Allocating units in order of greatest marginal cost reduction is therefore optimal
for a shared unit-capacity constraint.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import html
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CleaningSummary:
    source_rows: int
    cancellations_or_returns: int
    invalid_rows: int
    missing_descriptions: int
    accepted_rows: int


def _normalized_column(value: object) -> str:
    return str(value).strip().lower().replace(" ", "_")


def clean_transactions(frame: pd.DataFrame) -> tuple[pd.DataFrame, CleaningSummary]:
    """Normalize UCI-style retail columns and preserve transparent rejection counts."""
    aliases = {
        "invoice": "invoice",
        "invoiceno": "invoice",
        "stockcode": "sku",
        "description": "description",
        "quantity": "quantity",
        "invoicedate": "invoice_date",
        "price": "unit_price",
        "unitprice": "unit_price",
        "customer_id": "customer_id",
        "customerid": "customer_id",
        "country": "country",
    }
    renamed = {
        column: aliases.get(_normalized_column(column), _normalized_column(column))
        for column in frame.columns
    }
    data = frame.rename(columns=renamed).copy()
    required = {"invoice", "sku", "description", "quantity", "invoice_date", "unit_price", "country"}
    missing = sorted(required.difference(data.columns))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")

    data["invoice"] = data["invoice"].astype("string").fillna("").str.strip()
    data["sku"] = data["sku"].astype("string").fillna("").str.strip()
    data["description"] = data["description"].astype("string").fillna("").str.strip()
    data["country"] = data["country"].astype("string").fillna("").str.strip()
    data["quantity"] = pd.to_numeric(data["quantity"], errors="coerce")
    data["unit_price"] = pd.to_numeric(data["unit_price"], errors="coerce")
    data["invoice_date"] = pd.to_datetime(data["invoice_date"], errors="coerce")

    cancellation = data["invoice"].str.upper().str.startswith("C") | data["quantity"].le(0)
    invalid = (
        data["invoice_date"].isna()
        | data["quantity"].isna()
        | data["unit_price"].isna()
        | data["unit_price"].le(0)
        | data["sku"].eq("")
        | data["country"].eq("")
    )
    accepted_mask = ~(cancellation | invalid)
    accepted = data.loc[
        accepted_mask,
        ["invoice", "sku", "description", "quantity", "invoice_date", "unit_price", "country"],
    ].copy()
    accepted["quantity"] = accepted["quantity"].astype(float)
    accepted["unit_price"] = accepted["unit_price"].astype(float)

    summary = CleaningSummary(
        source_rows=len(data),
        cancellations_or_returns=int(cancellation.sum()),
        invalid_rows=int((invalid & ~cancellation).sum()),
        missing_descriptions=int(data["description"].eq("").sum()),
        accepted_rows=len(accepted),
    )
    return accepted, summary


def load_transactions(path: Path, sheet: str) -> tuple[pd.DataFrame, CleaningSummary]:
    frame = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    return clean_transactions(frame)


def _representative_description(values: pd.Series) -> str:
    usable = values.astype("string").fillna("").str.strip()
    usable = usable[usable.ne("")]
    if usable.empty:
        return "Unknown item"
    modes = usable.mode()
    return str(modes.iloc[0] if not modes.empty else usable.iloc[-1])


def weekly_demand_matrix(
    transactions: pd.DataFrame, country: str
) -> tuple[pd.DataFrame, pd.Series, pd.Series, int]:
    scoped = transactions.loc[transactions["country"].eq(country)].copy()
    if scoped.empty:
        available = ", ".join(sorted(transactions["country"].dropna().unique())[:12])
        raise ValueError(f"country {country!r} not found; examples: {available}")

    scoped["week"] = scoped["invoice_date"].dt.to_period("W-SUN").dt.start_time
    grouped = scoped.groupby(["week", "sku"], observed=True)["quantity"].sum()
    demand = grouped.unstack(fill_value=0.0).sort_index()
    full_weeks = pd.date_range(demand.index.min(), demand.index.max(), freq="7D")
    demand = demand.reindex(full_weeks, fill_value=0.0)
    demand.index.name = "week"

    prices = scoped.groupby("sku", observed=True)["unit_price"].median().reindex(demand.columns)
    descriptions = (
        scoped.groupby("sku", observed=True)["description"]
        .agg(_representative_description)
        .reindex(demand.columns)
    )
    return demand, prices.astype(float), descriptions.astype(str), len(scoped)


def select_skus(
    demand: pd.DataFrame,
    prices: pd.Series,
    train_weeks: int,
    top_skus: int,
    min_active_weeks: int,
) -> list[str]:
    train = demand.iloc[:train_weeks]
    active_weeks = train.gt(0).sum(axis=0)
    revenue_proxy = train.sum(axis=0) * prices
    eligible = active_weeks[active_weeks.ge(min_active_weeks)].index
    ranking = revenue_proxy.reindex(eligible).dropna().sort_values(ascending=False)
    selected = [str(value) for value in ranking.head(top_skus).index]
    if not selected:
        raise ValueError("no SKUs met the activity threshold")
    return selected


def backtest_forecasts(
    train: pd.DataFrame, test: pd.DataFrame, alpha: float = 0.30
) -> pd.DataFrame:
    records: list[tuple[str, float, float]] = []
    for sku in train.columns:
        history = [float(value) for value in train[sku].to_numpy()]
        level = history[0]
        for value in history[1:]:
            level = alpha * value + (1.0 - alpha) * level

        for actual in test[sku].to_numpy(dtype=float):
            predictions = {
                "Historical mean": float(np.mean(history)),
                "Trailing 4 weeks": float(np.mean(history[-4:])),
                "Exponential smoothing": float(level),
            }
            for method, prediction in predictions.items():
                records.append((method, prediction, float(actual)))
            history.append(float(actual))
            level = alpha * float(actual) + (1.0 - alpha) * level

    raw = pd.DataFrame(records, columns=["method", "prediction", "actual"])
    rows = []
    for method, group in raw.groupby("method", sort=False):
        error = group["prediction"] - group["actual"]
        denominator = float(group["actual"].abs().sum())
        rows.append(
            {
                "method": method,
                "wape": float(error.abs().sum() / denominator) if denominator else math.nan,
                "bias": float(error.sum() / denominator) if denominator else math.nan,
                "mae": float(error.abs().mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("wape", ignore_index=True)


def expected_cost(samples: Iterable[float], quantity: int, holding: float, shortage: float) -> float:
    values = np.asarray(list(samples), dtype=float)
    if values.size == 0:
        raise ValueError("expected_cost requires at least one demand sample")
    overage = np.maximum(float(quantity) - values, 0.0)
    underage = np.maximum(values - float(quantity), 0.0)
    return float(np.mean(holding * overage + shortage * underage))


def marginal_cost(samples: np.ndarray, quantity: int, holding: float, shortage: float) -> float:
    """Return C(q+1)-C(q) for an empirical integer-demand distribution."""
    cdf_at_q = float(np.mean(samples <= quantity))
    return (holding + shortage) * cdf_at_q - shortage


def newsvendor_quantities(
    train: pd.DataFrame, holding_costs: pd.Series, shortage_costs: pd.Series
) -> dict[str, int]:
    result: dict[str, int] = {}
    for sku in train.columns:
        holding = float(holding_costs[sku])
        shortage = float(shortage_costs[sku])
        critical_ratio = shortage / (holding + shortage)
        result[str(sku)] = int(
            np.quantile(train[sku].to_numpy(dtype=float), critical_ratio, method="higher")
        )
    return result


def optimize_capacity(
    train: pd.DataFrame,
    holding_costs: pd.Series,
    shortage_costs: pd.Series,
    capacity: int,
) -> dict[str, int]:
    """Solve the shared-unit capacity problem by marginal allocation."""
    if capacity < 0:
        raise ValueError("capacity must be non-negative")
    allocation = {str(sku): 0 for sku in train.columns}
    samples = {str(sku): train[sku].to_numpy(dtype=float) for sku in train.columns}
    heap: list[tuple[float, str]] = []
    for sku in allocation:
        delta = marginal_cost(
            samples[sku], 0, float(holding_costs[sku]), float(shortage_costs[sku])
        )
        heapq.heappush(heap, (delta, sku))

    for _ in range(capacity):
        delta, sku = heapq.heappop(heap)
        if delta >= 0:
            break
        allocation[sku] += 1
        next_delta = marginal_cost(
            samples[sku],
            allocation[sku],
            float(holding_costs[sku]),
            float(shortage_costs[sku]),
        )
        heapq.heappush(heap, (next_delta, sku))
    return allocation


def proportional_allocation(weights: Mapping[str, float], capacity: int) -> dict[str, int]:
    if capacity < 0:
        raise ValueError("capacity must be non-negative")
    keys = list(weights)
    values = np.asarray([max(float(weights[key]), 0.0) for key in keys], dtype=float)
    if values.sum() == 0 or capacity == 0:
        return {key: 0 for key in keys}
    raw = capacity * values / values.sum()
    base = np.floor(raw).astype(int)
    remaining = capacity - int(base.sum())
    order = np.argsort(-(raw - base), kind="stable")
    for index in order[:remaining]:
        base[index] += 1
    return {key: int(base[index]) for index, key in enumerate(keys)}


def evaluate_policy(
    test: pd.DataFrame,
    allocation: Mapping[str, int],
    prices: pd.Series,
    holding_rate: float,
    shortage_rate: float,
    policy: str,
) -> dict[str, float | int | str]:
    quantities = pd.Series(allocation, dtype=float).reindex(test.columns).fillna(0.0)
    demand = test.to_numpy(dtype=float)
    stock = np.broadcast_to(quantities.to_numpy(dtype=float), demand.shape)
    served = np.minimum(demand, stock)
    shortage_units = np.maximum(demand - stock, 0.0)
    leftover_units = np.maximum(stock - demand, 0.0)
    price = np.broadcast_to(prices.reindex(test.columns).to_numpy(dtype=float), demand.shape)
    holding_cost = float(np.sum(leftover_units * price * holding_rate))
    shortage_cost = float(np.sum(shortage_units * price * shortage_rate))
    total_demand = float(np.sum(demand))
    return {
        "policy": policy,
        "allocated_units": int(quantities.sum()),
        "fill_rate": float(np.sum(served) / total_demand) if total_demand else math.nan,
        "stockout_rate": float(np.mean(demand > stock)),
        "holding_cost": holding_cost,
        "shortage_cost": shortage_cost,
        "total_cost": holding_cost + shortage_cost,
    }


def _money(value: float) -> str:
    return f"£{value:,.0f}"


def write_qa_summary(
    path: Path,
    summary: CleaningSummary,
    country: str,
    country_rows: int,
    demand: pd.DataFrame,
    train_weeks: int,
    selected_skus: list[str],
) -> None:
    lines = [
        "# Data QA Summary",
        "",
        f"- Source rows: {summary.source_rows:,}",
        f"- Cancellations / returns excluded: {summary.cancellations_or_returns:,}",
        f"- Other invalid rows excluded: {summary.invalid_rows:,}",
        f"- Source rows missing descriptions: {summary.missing_descriptions:,}",
        f"- Accepted positive-sale rows: {summary.accepted_rows:,}",
        f"- Accepted rows in {country}: {country_rows:,}",
        f"- Weekly periods: {len(demand):,}",
        f"- Training weeks: {train_weeks:,}",
        f"- Holdout weeks: {len(demand) - train_weeks:,}",
        f"- Selected SKUs: {len(selected_skus):,}",
        "",
        "Returns and cancellations are excluded from demand rather than silently netted against sales. "
        "That makes the demand target interpretable, while the exclusion count remains visible for review.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_report(
    path: Path,
    sheet: str,
    country: str,
    train: pd.DataFrame,
    test: pd.DataFrame,
    capacity: int,
    forecast_metrics: pd.DataFrame,
    policy_results: pd.DataFrame,
    decisions: pd.DataFrame,
    holding_rate: float,
    shortage_rate: float,
) -> None:
    optimized = policy_results.loc[policy_results["policy"].eq("Optimized under capacity")].iloc[0]
    baseline = policy_results.loc[policy_results["policy"].eq("Proportional mean under capacity")].iloc[0]
    cost_reduction = (
        (float(baseline["total_cost"]) - float(optimized["total_cost"]))
        / float(baseline["total_cost"])
        if float(baseline["total_cost"])
        else 0.0
    )
    best_forecast = forecast_metrics.iloc[0]
    biggest = decisions.assign(
        shift=lambda data: data["optimized_qty"] - data["proportional_qty"]
    ).sort_values("shift", key=lambda values: values.abs(), ascending=False).head(8)

    lines = [
        "# Inventory Under Constraint",
        "",
        "## Decision summary",
        "",
        f"Using the same {capacity:,}-unit weekly capacity, the marginal optimizer reduced "
        f"holdout scenario cost by **{cost_reduction:.1%}** relative to proportional allocation. "
        f"Its demand fill rate was **{float(optimized['fill_rate']):.1%}**, compared with "
        f"**{float(baseline['fill_rate']):.1%}** for the baseline.",
        "",
        f"Across the forecast baselines, **{best_forecast['method']}** performed best with "
        f"**{float(best_forecast['wape']):.1%} WAPE** on the final {len(test)} weeks.",
        "",
        "## What was optimized",
        "",
        "For each SKU, weekly demand is represented by its empirical training distribution. "
        "The decision balances holding cost for leftover units against shortage cost for unmet demand:",
        "",
        "`min Σ hᵢ E[(qᵢ-Dᵢ)⁺] + pᵢ E[(Dᵢ-qᵢ)⁺]`, subject to `Σ qᵢ ≤ capacity`.",
        "",
        "Because each SKU's empirical expected-cost curve is discrete convex, allocating each "
        "additional unit to the SKU with the greatest marginal cost reduction gives the global "
        "optimum for the shared unit-capacity constraint.",
        "",
        "## Policy comparison",
        "",
        "| Policy | Units | Fill rate | Stockout SKU-weeks | Holding cost | Shortage cost | Scenario cost |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in policy_results.itertuples(index=False):
        lines.append(
            f"| {row.policy} | {row.allocated_units:,} | {row.fill_rate:.1%} | "
            f"{row.stockout_rate:.1%} | {_money(row.holding_cost)} | "
            f"{_money(row.shortage_cost)} | {_money(row.total_cost)} |"
        )
    lines.extend(
        [
            "",
            "## Largest allocation changes",
            "",
            "| SKU | Description | Proportional | Optimized | Shift |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for row in biggest.itertuples(index=False):
        description = str(row.description).replace("|", "/")[:54]
        shift = int(row.optimized_qty - row.proportional_qty)
        lines.append(
            f"| {row.sku} | {description} | {row.proportional_qty:,} | "
            f"{row.optimized_qty:,} | {shift:+,} |"
        )
    spike = decisions.sort_values("spike_ratio", ascending=False).iloc[0]
    lines.extend(
        [
            "",
            "## Why the largest shift matters",
            "",
            f"SKU `{spike['sku']}` contains a {int(spike['train_max']):,}-unit training week, "
            f"versus a typical positive week of {float(spike['train_positive_median']):,.1f} units "
            f"({float(spike['spike_ratio']):,.0f}x larger). That one event pulls its training mean "
            f"to {float(spike['train_mean']):,.1f} units and causes the proportional-mean baseline "
            f"to reserve {int(spike['proportional_qty']):,} units every week. The empirical optimizer "
            f"assigns {int(spike['optimized_qty']):,} instead because a rare bulk order does not justify "
            "permanent capacity under the stated cost assumptions.",
            "",
            "Operationally, the spike should be investigated rather than deleted automatically. If it "
            "was a known wholesale order, it belongs in a separate event/order channel; if it was an "
            "error, it belongs in source-data QA. Either way, a routine replenishment forecast should not "
            "treat it as ordinary weekly demand.",
            "",
            "## Evidence boundaries",
            "",
            f"- Source: UCI Online Retail II, sheet `{sheet}`, filtered to `{country}`.",
            f"- Train / holdout split: {len(train)} / {len(test)} weekly periods, in chronological order.",
            f"- Holding cost is a scenario assumption of {holding_rate:.1%} of unit price per leftover unit-week.",
            f"- Shortage cost is a scenario assumption of {shortage_rate:.1%} of unit price per unmet unit.",
            "- Unit price is observed; procurement cost, lead time, margin, shelf life, and service contracts are not.",
            "- A fixed weekly order-up-to quantity is evaluated against holdout demand. This is a decision lab, not a production inventory recommendation.",
            "- Product selection uses training-period activity and revenue only; holdout outcomes do not select SKUs.",
            "",
            "## Next operational questions",
            "",
            "1. How does the allocation change under supplier-specific lead times and case-pack constraints?",
            "2. Which SKUs retain priority across plausible holding/shortage cost scenarios?",
            "3. Does a rolling demand distribution outperform a fixed training distribution after demand shifts?",
            "4. What service-level commitments justify reserving capacity for low-volume, high-value SKUs?",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_svg(
    path: Path,
    policy_results: pd.DataFrame,
    forecast_metrics: pd.DataFrame,
    decisions: pd.DataFrame,
    capacity: int,
) -> None:
    width, height = 1200, 820
    background = "#f7f4ed"
    ink = "#17212b"
    navy = "#234a67"
    teal = "#2a7f77"
    coral = "#cf6b52"
    muted = "#64717b"
    grid = "#d9d5ca"

    optimized = policy_results.loc[policy_results["policy"].eq("Optimized under capacity")].iloc[0]
    baseline = policy_results.loc[policy_results["policy"].eq("Proportional mean under capacity")].iloc[0]
    reduction = (
        (float(baseline["total_cost"]) - float(optimized["total_cost"]))
        / float(baseline["total_cost"])
        if float(baseline["total_cost"])
        else 0.0
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{background}"/>',
        f'<text x="64" y="66" font-family="Arial, sans-serif" font-size="34" font-weight="700" fill="{ink}">Inventory under constraint</text>',
        f'<text x="64" y="98" font-family="Arial, sans-serif" font-size="17" fill="{muted}">Forecast backtest and empirical newsvendor allocation · final 12 weeks held out</text>',
    ]

    cards = [
        ("Weekly capacity", f"{capacity:,} units"),
        ("Scenario cost reduction", f"{reduction:.1%}"),
        ("Optimized fill rate", f"{float(optimized['fill_rate']):.1%}"),
        ("Selected SKUs", f"{len(decisions):,}"),
    ]
    for index, (label, value) in enumerate(cards):
        x = 64 + index * 274
        parts.extend(
            [
                f'<rect x="{x}" y="126" width="246" height="104" rx="12" fill="#ffffff" stroke="{grid}"/>',
                f'<text x="{x + 18}" y="158" font-family="Arial, sans-serif" font-size="15" fill="{muted}">{html.escape(label)}</text>',
                f'<text x="{x + 18}" y="203" font-family="Arial, sans-serif" font-size="29" font-weight="700" fill="{navy}">{html.escape(value)}</text>',
            ]
        )

    parts.append(
        f'<text x="64" y="282" font-family="Arial, sans-serif" font-size="21" font-weight="700" fill="{ink}">Holdout scenario cost</text>'
    )
    chart_x, chart_y, chart_w, chart_h = 64, 310, 510, 230
    max_cost = float(policy_results["total_cost"].max()) or 1.0
    colors = [teal, navy, coral, "#8b7ba8"]
    for index, row in enumerate(policy_results.itertuples(index=False)):
        y = chart_y + index * 52
        bar_width = chart_w * float(row.total_cost) / max_cost
        label = str(row.policy).replace(" under capacity", "")
        parts.extend(
            [
                f'<text x="{chart_x}" y="{y + 17}" font-family="Arial, sans-serif" font-size="14" fill="{ink}">{html.escape(label)}</text>',
                f'<rect x="{chart_x + 190}" y="{y}" width="{bar_width * 0.58:.1f}" height="23" rx="4" fill="{colors[index % len(colors)]}"/>',
                f'<text x="{chart_x + 200 + bar_width * 0.58:.1f}" y="{y + 17}" font-family="Arial, sans-serif" font-size="14" fill="{muted}">{html.escape(_money(float(row.total_cost)))}</text>',
            ]
        )

    parts.append(
        f'<text x="650" y="282" font-family="Arial, sans-serif" font-size="21" font-weight="700" fill="{ink}">Forecast WAPE</text>'
    )
    forecast_x, forecast_y = 650, 310
    max_wape = float(forecast_metrics["wape"].max()) or 1.0
    for index, row in enumerate(forecast_metrics.itertuples(index=False)):
        y = forecast_y + index * 62
        bar_width = 340 * float(row.wape) / max_wape
        parts.extend(
            [
                f'<text x="{forecast_x}" y="{y + 17}" font-family="Arial, sans-serif" font-size="14" fill="{ink}">{html.escape(str(row.method))}</text>',
                f'<rect x="{forecast_x}" y="{y + 27}" width="{bar_width:.1f}" height="20" rx="4" fill="{teal if index == 0 else navy}" opacity="{1.0 if index == 0 else 0.72}"/>',
                f'<text x="{forecast_x + bar_width + 10:.1f}" y="{y + 43}" font-family="Arial, sans-serif" font-size="14" fill="{muted}">{float(row.wape):.1%}</text>',
            ]
        )

    parts.append(
        f'<text x="64" y="592" font-family="Arial, sans-serif" font-size="21" font-weight="700" fill="{ink}">Largest optimizer reallocations</text>'
    )
    shifts = decisions.assign(
        shift=lambda data: data["optimized_qty"] - data["proportional_qty"]
    ).sort_values("shift", key=lambda values: values.abs(), ascending=False).head(8)
    max_shift = max(float(shifts["shift"].abs().max()), 1.0)
    center_x = 780
    parts.append(f'<line x1="{center_x}" y1="620" x2="{center_x}" y2="790" stroke="{grid}" stroke-width="2"/>')
    for index, row in enumerate(shifts.itertuples(index=False)):
        y = 626 + index * 20
        shift = float(row.optimized_qty - row.proportional_qty)
        bar = 300 * abs(shift) / max_shift
        x = center_x if shift >= 0 else center_x - bar
        color = teal if shift >= 0 else coral
        description = str(row.description)[:34]
        parts.extend(
            [
                f'<text x="64" y="{y + 13}" font-family="Arial, sans-serif" font-size="13" fill="{ink}">{html.escape(str(row.sku))} · {html.escape(description)}</text>',
                f'<rect x="{x:.1f}" y="{y}" width="{bar:.1f}" height="14" rx="2" fill="{color}"/>',
                f'<text x="{1090}" y="{y + 13}" text-anchor="end" font-family="Arial, sans-serif" font-size="13" fill="{muted}">{shift:+.0f}</text>',
            ]
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_sqlite(
    path: Path,
    demand: pd.DataFrame,
    decisions: pd.DataFrame,
    forecast_metrics: pd.DataFrame,
    policy_results: pd.DataFrame,
) -> None:
    long_demand = demand.reset_index().melt(id_vars="week", var_name="sku", value_name="demand")
    long_demand["week"] = long_demand["week"].dt.strftime("%Y-%m-%d")
    with sqlite3.connect(path) as connection:
        long_demand.to_sql("weekly_demand", connection, if_exists="replace", index=False)
        decisions.to_sql("sku_decisions", connection, if_exists="replace", index=False)
        forecast_metrics.to_sql("forecast_metrics", connection, if_exists="replace", index=False)
        policy_results.to_sql("policy_results", connection, if_exists="replace", index=False)


def run_analysis(args: argparse.Namespace) -> None:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    transactions, cleaning = load_transactions(Path(args.input), args.sheet)
    demand_all, prices_all, descriptions_all, country_rows = weekly_demand_matrix(
        transactions, args.country
    )
    if args.test_weeks <= 0 or args.test_weeks >= len(demand_all):
        raise ValueError("test-weeks must be positive and smaller than the number of weekly periods")
    train_weeks = len(demand_all) - args.test_weeks
    selected = select_skus(
        demand_all,
        prices_all,
        train_weeks,
        args.top_skus,
        args.min_active_weeks,
    )
    demand = demand_all[selected].copy()
    prices = prices_all.reindex(selected)
    descriptions = descriptions_all.reindex(selected)
    train = demand.iloc[:train_weeks]
    test = demand.iloc[train_weeks:]

    forecast_metrics = backtest_forecasts(train, test, alpha=args.alpha)
    holding_costs = prices * args.holding_rate
    shortage_costs = prices * args.shortage_rate
    unconstrained = newsvendor_quantities(train, holding_costs, shortage_costs)
    capacity = max(1, int(math.floor(args.capacity_ratio * sum(unconstrained.values()))))
    proportional = proportional_allocation(train.mean(axis=0).to_dict(), capacity)
    optimized = optimize_capacity(train, holding_costs, shortage_costs, capacity)
    mean_policy = {str(sku): int(round(float(train[sku].mean()))) for sku in train.columns}

    policies = [
        ("Optimized under capacity", optimized),
        ("Proportional mean under capacity", proportional),
        ("Newsvendor unconstrained", unconstrained),
        ("Historical mean unconstrained", mean_policy),
    ]
    policy_results = pd.DataFrame(
        [
            evaluate_policy(
                test,
                allocation,
                prices,
                args.holding_rate,
                args.shortage_rate,
                name,
            )
            for name, allocation in policies
        ]
    ).sort_values("total_cost", ignore_index=True)

    decisions = pd.DataFrame(
        {
            "sku": selected,
            "description": descriptions.reindex(selected).to_numpy(),
            "unit_price": prices.reindex(selected).to_numpy(dtype=float),
            "train_mean": train.mean(axis=0).reindex(selected).to_numpy(dtype=float),
            "train_std": train.std(axis=0).reindex(selected).to_numpy(dtype=float),
            "train_positive_median": train.apply(
                lambda column: column[column.gt(0)].median(), axis=0
            ).reindex(selected).to_numpy(dtype=float),
            "train_max": train.max(axis=0).reindex(selected).to_numpy(dtype=float),
            "active_train_weeks": train.gt(0).sum(axis=0).reindex(selected).to_numpy(dtype=int),
            "proportional_qty": [proportional[sku] for sku in selected],
            "optimized_qty": [optimized[sku] for sku in selected],
            "newsvendor_qty": [unconstrained[sku] for sku in selected],
        }
    )
    decisions["spike_ratio"] = decisions["train_max"] / decisions["train_positive_median"].clip(lower=1.0)

    forecast_metrics.to_csv(output / "forecast_metrics.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    policy_results.to_csv(output / "policy_comparison.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    decisions.to_csv(output / "sku_decisions.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    write_qa_summary(
        output / "qa_summary.md",
        cleaning,
        args.country,
        country_rows,
        demand,
        train_weeks,
        selected,
    )
    write_report(
        output / "insight_report.md",
        args.sheet,
        args.country,
        train,
        test,
        capacity,
        forecast_metrics,
        policy_results,
        decisions,
        args.holding_rate,
        args.shortage_rate,
    )
    write_svg(output / "decision_summary.svg", policy_results, forecast_metrics, decisions, capacity)
    write_sqlite(output / "replenishment.db", demand, decisions, forecast_metrics, policy_results)

    best = policy_results.iloc[0]
    print(
        f"wrote {output} | {len(selected)} SKUs | {capacity} capacity | "
        f"best policy: {best['policy']} ({_money(float(best['total_cost']))})"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser("analyze", help="run the real-data decision analysis")
    analyze.add_argument("--input", required=True, help="path to online_retail_II.xlsx")
    analyze.add_argument("--sheet", default="Year 2010-2011")
    analyze.add_argument("--country", default="United Kingdom")
    analyze.add_argument("--output", default="exports")
    analyze.add_argument("--top-skus", type=int, default=20)
    analyze.add_argument("--min-active-weeks", type=int, default=20)
    analyze.add_argument("--test-weeks", type=int, default=12)
    analyze.add_argument("--capacity-ratio", type=float, default=0.85)
    analyze.add_argument("--holding-rate", type=float, default=0.05)
    analyze.add_argument("--shortage-rate", type=float, default=0.30)
    analyze.add_argument("--alpha", type=float, default=0.30)
    analyze.set_defaults(func=run_analysis)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
