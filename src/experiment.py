"""The study: configuration, cohort, capacity, a year of weekly re-planning, the
predeclared sensitivities, paired block-bootstrap intervals and the bridge from the
originally published design.

Information timing. The stock decision for the week starting Monday t uses only what
was recorded before t: history samples come from sales as known at t (a reversal
removal applies once its credit is recorded), prices from kept lines in the 52 weeks
before t. The sales scored in week w apply the removals known by the end of that week
(cutoff w + 7 days), so a removal learned later never rewinds simulated stock. The
cohort and the capacity are fixed once, as known when the evaluation year starts.
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd

import data
import model

WEEK = data.WEEK
POLICIES = {
    "proportional": "Proportional to recent mean",
    "scaled_fractile": "Scaled critical-fractile",
    "optimizer": "Marginal optimizer",
    "optimizer_unit": "Marginal optimizer, equal prices",
    "unconstrained": "Unconstrained newsvendor",
}
REFERENCES = ("unconstrained",)  # ignores the capacity; shown for reference only
WINDOWS = {  # name: (label, weeks back to the first sample week, number of weeks)
    "trailing_52": ("Trailing 52 weeks", 52, 52),
    "trailing_13": ("Trailing 13 weeks", 13, 13),
    "seasonal_analog": ("Same 13 weeks a year earlier", 52, 13),
}
PRICE_WEEKS = 52
CLOSURES = ("drop", "zero")  # weeks without invoices: dropped from history, or kept as zeros
BRIDGE_STEPS = {
    "original": "Published design",
    "prompt_reversals": "Remove sales reversed within {hours} hours",
    "code_registry": "Exclude charge, accounting, voucher and manual codes",
    "case_normalization": "Merge stock codes that differ only in case",
    "complete_weeks": "Complete weeks only",
    "training_prices": "Prices from the training weeks only",
    "inverse_ecdf_capacity": "Capacity from the smallest optimal quantities",
}


class ConfigError(ValueError):
    pass


# Configuration ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    rules: data.DataRules
    window: str
    closures: str
    capacity_factor: Fraction
    holding_rate: Fraction
    shortage_rate: Fraction
    bulk_cap: Fraction | None = None

    @property
    def critical_ratio(self) -> Fraction:
        return model.critical_ratio(self.holding_rate, self.shortage_rate)


@dataclass(frozen=True)
class Config:
    sha256: str
    size: int
    country: str
    reversal_hours: int
    skus: int
    min_active_weeks: int
    selection_weeks: int
    evaluation_weeks: int
    baselines: tuple[str, ...]
    primary: Scenario
    sensitivities: tuple[Scenario, ...]
    block_weeks: int
    check_block_weeks: tuple[int, ...]
    resamples: int
    seed: int
    confidence: Fraction
    bridge_sheet: str
    bridge_skus: int
    bridge_min_active_weeks: int
    bridge_holdout_weeks: int
    bridge_capacity_share: Fraction
    bridge_steps: tuple[str, ...]


def _keys(table, allowed, name, required=()):
    if not isinstance(table, dict):
        raise ConfigError(f"{name} must be a table")
    unknown, missing = set(table) - set(allowed), set(required) - set(table)
    if unknown or missing:
        raise ConfigError(f"{name}: unknown keys {sorted(unknown)}, missing keys {sorted(missing)}")
    return table


def _exact(value, name, positive=False, below_one=False) -> Fraction:
    """A finite non-negative number, exactly as written (0.05 is 1/20)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"{name} must be a finite number, got {value!r}")
    exact = Fraction(repr(value)) if isinstance(value, float) else Fraction(value)
    if exact < 0 or (positive and exact == 0) or (below_one and exact >= 1):
        bounds = "between 0 and 1" if below_one else "positive" if positive else "non-negative"
        raise ConfigError(f"{name} must be {bounds}, got {value!r}")
    return exact


def _count(value, name, minimum=1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{name} must be a whole number of at least {minimum}, got {value!r}")
    return value


def _choice(value, options, name) -> str:
    if not isinstance(value, str) or value not in options:
        raise ConfigError(f"{name} must be one of {sorted(options)}, got {value!r}")
    return value


SCENARIO_KEYS = ("id", "label", "data", "window", "closure_weeks", "capacity_factor", "holding_rate",
                 "shortage_rate", "critical_ratio", "bulk_cap_quantile")
TREATMENT_KEYS = ("data", "closure_weeks", "bulk_cap_quantile")  # changed only by sensitivities


def _scenario(table, base: Scenario | None) -> Scenario:
    """The primary scenario (no base), or a sensitivity, which keeps every primary setting it
    does not change.

    The primary always uses the primary data treatment: `data.PRIMARY_RULES`, closure weeks
    dropped from history and no bulk cap. The SQL check and the reports' description of the
    data assume it.
    """
    required = ("id", "label") + (() if base else ("window", "capacity_factor", "holding_rate", "shortage_rate"))
    _keys(table, SCENARIO_KEYS, "a scenario", required)
    fixed = [key for key in TREATMENT_KEYS if key in table]
    if base is None and fixed:
        raise ConfigError(f"[primary] cannot set {', '.join(fixed)}: the primary data treatment is fixed "
                          "(see data/README.md), and only a [[sensitivity]] row changes it")
    name = f"scenario {table['id']!r}"
    rules = dict(vars(base.rules if base else data.PRIMARY_RULES))
    rules.update(_keys(table.get("data", {}), ("reversals", "registry", "normalize_case"), f"{name} data"))
    try:
        rules = data.DataRules(**rules)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{name}: {error}") from None
    holding = _exact(table["holding_rate"], f"{name} holding_rate") if "holding_rate" in table else base.holding_rate
    shortage = _exact(table["shortage_rate"], f"{name} shortage_rate") if "shortage_rate" in table else base.shortage_rate
    if "critical_ratio" in table:  # holding fixed, shortage = holding * r / (1 - r)
        ratio = _exact(table["critical_ratio"], f"{name} critical_ratio", positive=True, below_one=True)
        shortage = holding * ratio / (1 - ratio)
    if holding == 0 and shortage == 0:
        raise ConfigError(f"{name}: holding_rate and shortage_rate cannot both be zero")
    cap = base.bulk_cap if base else None
    if "bulk_cap_quantile" in table:
        cap = _exact(table["bulk_cap_quantile"], f"{name} bulk_cap_quantile", positive=True)
        if cap > 1:
            raise ConfigError(f"{name}: bulk_cap_quantile must be at most 1")
    return Scenario(
        id=str(table["id"]), label=str(table["label"]), rules=rules,
        window=_choice(table.get("window", base and base.window), WINDOWS, f"{name} window"),
        closures=_choice(table.get("closure_weeks", base.closures if base else "drop"), CLOSURES,
                         f"{name} closure_weeks"),
        capacity_factor=(_exact(table["capacity_factor"], f"{name} capacity_factor")
                         if "capacity_factor" in table else base.capacity_factor),
        holding_rate=holding, shortage_rate=shortage, bulk_cap=cap,
    )


TABLES = {  # every key is required
    "input": ("sha256", "bytes", "country", "reversal_window_hours"),
    "cohort": ("skus", "min_active_weeks", "selection_weeks", "evaluation_weeks"),
    "comparison": ("baselines",),
    "bootstrap": ("block_weeks", "check_block_weeks", "resamples", "seed", "confidence"),
    "bridge": ("sheet", "skus", "min_active_weeks", "holdout_weeks", "capacity_share", "steps"),
}
COUNTS = {  # Config field: (table, key, smallest value allowed)
    "size": ("input", "bytes", 1), "reversal_hours": ("input", "reversal_window_hours", 0),
    "skus": ("cohort", "skus", 1), "min_active_weeks": ("cohort", "min_active_weeks", 0),
    "selection_weeks": ("cohort", "selection_weeks", 1), "evaluation_weeks": ("cohort", "evaluation_weeks", 1),
    "resamples": ("bootstrap", "resamples", 1), "seed": ("bootstrap", "seed", 0),
    "bridge_skus": ("bridge", "skus", 1), "bridge_min_active_weeks": ("bridge", "min_active_weeks", 0),
    "bridge_holdout_weeks": ("bridge", "holdout_weeks", 1),
}


def parse_config(raw: dict) -> Config:
    _keys(raw, (*TABLES, "primary", "sensitivity"), "config", (*TABLES, "primary"))
    for name, keys in TABLES.items():
        _keys(raw[name], keys, name, keys)
    counts = {field: _count(raw[table][key], f"{table} {key}", low) for field, (table, key, low) in COUNTS.items()}
    source, compare, boot, bridge = raw["input"], raw["comparison"], raw["bootstrap"], raw["bridge"]
    if not isinstance(raw.get("sensitivity", []), list):
        raise ConfigError("sensitivities must be an array of tables, [[sensitivity]]")
    primary = _scenario(raw["primary"], None)
    sensitivities = tuple(_scenario(table, primary) for table in raw.get("sensitivity", []))
    if len({scenario.id for scenario in (primary, *sensitivities)}) != 1 + len(sensitivities):
        raise ConfigError("scenario ids must be unique")
    sha = source["sha256"]
    if not (isinstance(sha, str) and len(sha) == 64 and set(sha) <= set("0123456789abcdef")):
        raise ConfigError("input sha256 must be 64 lowercase hex digits")
    if counts["min_active_weeks"] > counts["selection_weeks"]:
        raise ConfigError("min_active_weeks cannot exceed selection_weeks")
    if not isinstance(compare["baselines"], list) or not compare["baselines"]:
        raise ConfigError("comparison baselines must be a non-empty list")
    baselines = tuple(_choice(name, set(POLICIES) - {"optimizer"}, "comparison baseline")
                      for name in compare["baselines"])
    if not isinstance(boot["check_block_weeks"], list):
        raise ConfigError("check_block_weeks must be a list")
    blocks = tuple(_count(value, "bootstrap block length") for value in [boot["block_weeks"], *boot["check_block_weeks"]])
    if max(blocks) > counts["evaluation_weeks"]:
        raise ConfigError("bootstrap blocks cannot be longer than the evaluation weeks")
    steps = bridge["steps"]
    if not isinstance(steps, list) or not steps or steps[0] != "original" or len(set(map(str, steps))) != len(steps):
        raise ConfigError("bridge steps must be distinct and start with 'original'")
    for step in steps:
        _choice(step, BRIDGE_STEPS, "bridge step")
    if not isinstance(source["country"], str):
        raise ConfigError("country must be text")
    return Config(
        sha256=sha, country=source["country"], baselines=baselines, primary=primary,
        sensitivities=sensitivities, block_weeks=blocks[0], check_block_weeks=blocks[1:],
        confidence=_exact(boot["confidence"], "confidence", positive=True, below_one=True),
        bridge_sheet=_choice(bridge["sheet"], data.SHEETS, "bridge sheet"),
        bridge_capacity_share=_exact(bridge["capacity_share"], "bridge capacity_share"),
        bridge_steps=tuple(steps), **counts)


def load_config(path) -> Config:
    """Read and validate a configuration file; nothing else is touched before this passes."""
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from None
    return parse_config(raw)


def capacity_units(factor: Fraction, mean: Fraction) -> int:
    """round(factor * mean), halves rounded up, exactly."""
    return math.floor(factor * mean + Fraction(1, 2))


# The study --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Plan:
    """What a decision for one week may use."""

    histories: dict
    prices: dict
    means: dict


class Study:
    """The ledger, calendar, cohort and capacity basis shared by every scenario."""

    def __init__(self, config: Config, ledger: pd.DataFrame):
        self.config, self.ledger = config, ledger
        self.calendar = data.calendar(ledger)
        weeks = self.calendar.set_index("week_start")
        self.complete = weeks.index[weeks["complete"]]
        self.closures = weeks.index[weeks["closure"]]
        if len(self.complete) < config.selection_weeks + config.evaluation_weeks:
            raise ValueError(f"the data has {len(self.complete)} complete weeks; the configuration needs "
                             f"{config.selection_weeks + config.evaluation_weeks}")
        self.selection = self.complete[:config.selection_weeks]
        self.evaluation = self.complete[config.selection_weeks:config.selection_weeks + config.evaluation_weeks]
        self._panels, self._matrices, self._prices = {}, {}, {}
        self.cohort, self.mean_units, self.selection_table = self._select()

    def panel(self, rules: data.DataRules) -> data.SalesPanel:
        if rules not in self._panels:
            self._panels[rules] = data.SalesPanel(self.ledger, rules, self.config.country)
        return self._panels[rules]

    def matrix(self, rules, cutoff) -> pd.DataFrame:
        """Weeks x cohort sales as known at the cutoff (cached)."""
        key = (rules, cutoff)
        if key not in self._matrices:
            self._matrices[key] = self.panel(rules).matrix(cutoff, skus=self.cohort)
        return self._matrices[key]

    def _select(self):
        """The cohort: SKUs sold in enough selection weeks, by selection-year revenue."""
        start, rules = self.evaluation[0], self.config.primary.rules
        panel = self.panel(rules)
        units = panel.matrix(start).loc[self.selection]
        weekly = panel.weekly(start)
        revenue = weekly.loc[weekly["week_start"].isin(self.selection)].groupby("sku")["revenue"].sum()
        table = pd.DataFrame({"active_weeks": units.gt(0).sum(), "units": units.sum()})
        table["revenue"] = revenue.reindex(table.index).fillna(0.0)
        table = table.loc[table["active_weeks"].ge(self.config.min_active_weeks) & table["units"].gt(0)]
        table = table.rename_axis("sku").reset_index().sort_values(["revenue", "sku"], ascending=[False, True])
        table = table.head(self.config.skus).reset_index(drop=True)
        if table.empty:
            raise ValueError("no SKU meets the selection rule")
        cohort = tuple(table["sku"])
        open_weeks = self.selection.difference(self.closures)
        mean = Fraction(int(units.loc[open_weeks, list(cohort)].to_numpy().sum()), len(open_weeks))
        return cohort, mean, table

    def history_weeks(self, t, window, closures) -> pd.DatetimeIndex:
        _, back, length = WINDOWS[window]
        weeks = pd.date_range(t - back * WEEK, periods=length, freq="7D")
        weeks = weeks[weeks.isin(self.complete)]
        if closures == "drop":
            weeks = weeks[~weeks.isin(self.closures)]
        if weeks.empty:
            raise ValueError(f"no history weeks for the decision week {t.date()}")
        return weeks

    def prices(self, rules, t) -> dict:
        """Median unit price of each cohort SKU over the 52 weeks before t, as known at t."""
        key = (rules, t)
        if key not in self._prices:
            panel = self.panel(rules)
            price = panel.prices(t - PRICE_WEEKS * WEEK, t, cutoff=t, skus=self.cohort)
            if price.isna().any():
                raise ValueError(f"no sale in the {PRICE_WEEKS} weeks before {t.date()} gives a price for "
                                 + ", ".join(price.index[price.isna()]))
            self._prices[key] = price.to_dict()
        return self._prices[key]

    def plan(self, scenario: Scenario, t) -> Plan:
        weeks = self.history_weeks(t, scenario.window, scenario.closures)
        rules = scenario.rules
        if scenario.bulk_cap is None:
            matrix = self.matrix(rules, t)
        else:  # caps from the history window, history only
            panel = self.panel(rules)
            caps = panel.bulk_caps(weeks[0], weeks[-1] + WEEK, cutoff=t, quantile=str(scenario.bulk_cap))
            matrix = panel.matrix(t, skus=self.cohort, caps=caps)
        samples = matrix.loc[weeks]
        histories = {sku: samples[sku].tolist() for sku in self.cohort}
        means = {sku: Fraction(sum(values), len(values)) for sku, values in histories.items()}
        return Plan(histories, self.prices(rules, t), means)

    def scored_sales(self, rules) -> np.ndarray:
        """Evaluation weeks x cohort: each week's sales as known at its close."""
        return np.vstack([self.matrix(rules, t + WEEK).loc[t].to_numpy() for t in self.evaluation])


def decide(policy, plan: Plan, targets: dict, carried: dict, capacity: int, h, p) -> dict:
    """Start-of-week stock for one policy; `targets` are the plan's newsvendor quantities."""
    if policy == "optimizer":
        return model.optimize_capacity(plan.histories, plan.prices, h, p, capacity, floors=carried)
    if policy == "optimizer_unit":
        return model.optimize_capacity(plan.histories, None, h, p, capacity, floors=carried)
    if policy == "scaled_fractile":
        return model.fill_gaps(model.scale_to_capacity(targets, capacity), carried, capacity)
    if policy == "proportional":
        return model.fill_gaps(model.proportional_allocation(plan.means, capacity), carried, capacity)
    if policy == "unconstrained":
        return model.fill_gaps(targets, carried, None)
    raise ValueError(f"unknown policy {policy!r}")


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    capacity: int
    weeks: pd.DatetimeIndex
    prices: np.ndarray
    runs: dict  # policy id -> model.Simulation
    comparisons: list  # one per baseline, see compare()


def run_scenario(study: Study, scenario: Scenario, blocks=None) -> ScenarioResult:
    capacity = capacity_units(scenario.capacity_factor, study.mean_units)
    h, p = scenario.holding_rate, scenario.shortage_rate
    plans = [study.plan(scenario, t) for t in study.evaluation]
    targets = [model.newsvendor_targets(plan.histories, h, p) for plan in plans]
    prices = np.array([[plan.prices[sku] for sku in study.cohort] for plan in plans])
    sales = study.scored_sales(scenario.rules)
    runs = {}
    for policy in POLICIES:
        def choose(week, carried, policy=policy):
            return decide(policy, plans[week], targets[week], carried, capacity, h, p)
        limit = None if policy in REFERENCES else capacity
        runs[policy] = model.simulate(study.cohort, sales, prices, choose, limit, h, p)
    config = study.config
    blocks = blocks or (config.block_weeks,)
    samples = {block: block_indices(len(study.evaluation), block, config.resamples, config.seed) for block in blocks}
    reference = runs["optimizer"].cost.sum(axis=1)
    comparisons = [dict(baseline=baseline, **compare(reference, runs[baseline].cost.sum(axis=1), samples,
                                                     config.confidence))
                   for baseline in config.baselines]
    return ScenarioResult(scenario, capacity, study.evaluation, prices, runs, comparisons)


# Comparisons ------------------------------------------------------------------------------


def relative(a, b):
    """a / b - 1, elementwise: 0 when both are zero, NaN when only b is."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    safe = np.where(b != 0, b, 1.0)
    return np.where(b != 0, a / safe - 1, np.where(a == 0, 0.0, np.nan))


def block_indices(weeks: int, block: int, resamples: int, seed: int) -> np.ndarray:
    """Moving-block resamples of week positions, (resamples x weeks), reproducible per block length."""
    block = min(block, weeks)
    rng = np.random.default_rng([seed, block])
    starts = rng.integers(0, weeks - block + 1, size=(resamples, -(-weeks // block)))
    return (starts[:, :, None] + np.arange(block)).reshape(resamples, -1)[:, :weeks]


def compare(policy_cost, baseline_cost, samples, confidence) -> dict:
    """Paired comparison of two weekly cost series: totals, intervals, weeks won and lost.

    `samples` maps a block length to its resampled week positions; the interval is the
    percentile interval of the resampled total difference and relative difference.
    """
    a, b = np.asarray(policy_cost, float), np.asarray(baseline_cost, float)
    tail = (1 - float(confidence)) / 2
    result = {
        "policy_cost": float(a.sum()), "baseline_cost": float(b.sum()), "difference": float(a.sum() - b.sum()),
        "relative": float(relative(a.sum(), b.sum())),
        "weeks_won": int((a < b).sum()), "weeks_lost": int((a > b).sum()), "weeks_tied": int((a == b).sum()),
        "intervals": {},
    }
    for block, positions in samples.items():
        total_a, total_b = a[positions].sum(axis=1), b[positions].sum(axis=1)
        low, high = np.quantile(total_a - total_b, [tail, 1 - tail])
        rel_low, rel_high = np.quantile(relative(total_a, total_b), [tail, 1 - tail])
        result["intervals"][block] = {"difference": [float(low), float(high)],
                                      "relative": [float(rel_low), float(rel_high)]}
    return result


def policy_summary(run: model.Simulation, capacity: int) -> dict:
    sales, starts = run.sales.sum(), run.start.sum(axis=1)
    return {
        "allocated_units": float(starts.mean()), "fill_rate": float(run.covered.sum() / sales) if sales else math.nan,
        "stockout_rate": float((run.lost > 0).mean()), "holding_cost": float(run.holding_cost.sum()),
        "shortage_cost": float(run.shortage_cost.sum()), "total_cost": float(run.cost.sum()),
        "ordered_units": int(run.ordered.sum()), "leftover_units": float(run.closing.sum(axis=1).mean()),
        "max_start_units": int(starts.max()), "within_capacity": bool(starts.max() <= capacity),
    }


def quarters(result: ScenarioResult, parts=4) -> pd.DataFrame:
    """Each policy's modeled cost over consecutive blocks of the evaluation weeks."""
    rows = []
    for number, positions in enumerate(np.array_split(np.arange(len(result.weeks)), parts), 1):
        if positions.size == 0:
            continue
        row = {"quarter": number, "first_week": result.weeks[positions[0]], "weeks": positions.size,
               "last_week": result.weeks[positions[-1]]}
        row.update({policy: float(run.cost[positions].sum()) for policy, run in result.runs.items()})
        rows.append(row)
    return pd.DataFrame(rows)


def sku_contributions(result: ScenarioResult) -> pd.DataFrame:
    """Per-SKU modeled cost and coverage of each policy over the evaluation weeks."""
    frame = pd.DataFrame(index=pd.Index(result.runs["optimizer"].skus, name="sku"))
    for policy, run in result.runs.items():
        frame[f"{policy}_cost"] = run.cost.sum(axis=0)
        sales = run.sales.sum(axis=0)
        frame[f"{policy}_fill_rate"] = np.divide(run.covered.sum(axis=0), sales, out=np.full(sales.shape, np.nan),
                                                 where=sales > 0)
    frame["sales_units"] = result.runs["optimizer"].sales.sum(axis=0)
    return frame.reset_index()


def forecast_metrics(study: Study, scenario: Scenario) -> pd.DataFrame:
    """Each history window's mean as a one-week-ahead forecast of the scored sales, and its
    critical-ratio quantile (the unconstrained decision) scored by pinball loss."""
    actual = study.scored_sales(scenario.rules).astype(float)
    ratio, rows = float(scenario.critical_ratio), []
    for window, (label, _, _) in WINDOWS.items():
        plans = [study.plan(replace(scenario, window=window), t) for t in study.evaluation]
        mean = np.array([[float(plan.means[sku]) for sku in study.cohort] for plan in plans])
        quantile = np.array([list(model.newsvendor_targets(plan.histories, scenario.holding_rate,
                                                           scenario.shortage_rate).values()) for plan in plans])
        error, total = mean - actual, actual.sum()
        loss = ratio * np.maximum(actual - quantile, 0) + (1 - ratio) * np.maximum(quantile - actual, 0)
        rows.append({"method": label, "wape": np.abs(error).sum() / total if total else math.nan,
                     "bias": error.sum() / total if total else math.nan, "mae": np.abs(error).mean(),
                     "pinball_loss": loss.mean(), "window": window})
    return pd.DataFrame(rows)


def next_targets(study: Study, scenario: Scenario) -> pd.DataFrame:
    """The stock each policy would set for the week after the evaluation weeks (nothing
    carried), with the statistics of the history window it uses."""
    t = study.evaluation[-1] + WEEK
    plan, weeks = study.plan(scenario, t), study.history_weeks(t, scenario.window, scenario.closures)
    end = weeks[-1] + WEEK
    h, p = scenario.holding_rate, scenario.shortage_rate
    capacity = capacity_units(scenario.capacity_factor, study.mean_units)
    newsvendor = model.newsvendor_targets(plan.histories, h, p)
    history = pd.DataFrame(plan.histories)
    panel = study.panel(scenario.rules)
    shares = panel.concentration(weeks[0], end, cutoff=t, skus=study.cohort)
    frame = pd.DataFrame({
        "sku": list(study.cohort),
        "description": panel.descriptions(weeks[0], end, skus=study.cohort).to_numpy(),
        "unit_price": [plan.prices[sku] for sku in study.cohort],
        "train_mean": history.mean().to_numpy(), "train_std": history.std().to_numpy(),
        "train_positive_median": history.where(history > 0).median().to_numpy(),
        "train_max": history.max().to_numpy(), "active_train_weeks": history.gt(0).sum().to_numpy(),
        "proportional_qty": list(model.proportional_allocation(plan.means, capacity).values()),
        "optimized_qty": list(model.optimize_capacity(plan.histories, plan.prices, h, p, capacity).values()),
        "newsvendor_qty": list(newsvendor.values()),
    })
    frame["spike_ratio"] = frame["train_max"] / frame["train_positive_median"].clip(lower=1.0)
    frame["scaled_fractile_qty"] = list(model.scale_to_capacity(newsvendor, capacity).values())
    for column in ("anonymous_share", "top_customer_share", "top_invoice_share"):
        frame[column] = shares[column].to_numpy()
    frame["decision_week"] = t
    return frame


def largest_week(study: Study, scenario: Scenario) -> dict:
    """The cohort's largest SKU-week against its typical selling week, its largest line,
    and that line's matched credit if one exists."""
    panel, weeks = study.panel(scenario.rules), study.selection.append(study.evaluation)
    matrix = panel.matrix(None, skus=study.cohort).loc[weeks]
    typical = matrix.where(matrix > 0).median()
    ratio = matrix.max() / typical.clip(lower=1.0)
    sku = str(ratio.idxmax())
    week = matrix[sku].idxmax()
    lines = panel.window(week, week + WEEK)
    lines = lines.loc[lines["sku"].eq(sku)]
    top = lines.loc[lines["quantity"].idxmax()]
    ledger = study.ledger
    row = ledger.loc[ledger["invoice"].eq(top["invoice"]) & ledger["sku"].eq(sku)
                     & ledger["quantity"].eq(top["quantity"]) & ledger["timestamp"].eq(top["timestamp"])]
    pair = row["pair_row"].dropna()
    credit = None
    if len(pair):
        other = ledger.loc[int(pair.iloc[0])]
        credit = {"invoice": str(other["invoice"]), "time": other["timestamp"], "role": str(other["role"]),
                  "lag_days": (other["timestamp"] - top["timestamp"]) / pd.Timedelta(1, "D")}
    return {"sku": sku, "description": panel.descriptions(skus=[sku]).iloc[0], "week": week,
            "units": int(matrix.at[week, sku]), "typical_units": float(typical[sku]), "ratio": float(ratio[sku]),
            "invoice": str(top["invoice"]), "line_units": int(top["quantity"]), "line_time": top["timestamp"],
            "anonymous": bool(pd.isna(top["customer_id"])), "credit": credit}


def fixed_design(histories: dict, sales, prices: dict, rates, share, smallest_optimum: bool):
    """The original design's capacity, floor(share x the total unconstrained quantity), and the
    holdout cost of fixed targets for the optimizer and the two baselines. The quantities are
    NumPy's 'higher' critical-ratio quantiles unless `smallest_optimum` asks for the smallest
    optima; `sales` is holdout weeks x SKUs in `histories` order."""
    skus = list(histories)
    quantiles = model.newsvendor_targets if smallest_optimum else model.upper_quantile_targets
    capacity = math.floor(share * sum(quantiles(histories, *rates).values()))
    means = {sku: Fraction(sum(values), len(values)) for sku, values in histories.items()}
    targets = {
        "optimizer": model.optimize_capacity(histories, prices, *rates, capacity),
        "scaled_fractile": model.scale_to_capacity(model.newsvendor_targets(histories, *rates), capacity),
        "proportional": model.proportional_allocation(means, capacity),
    }
    return capacity, {policy: float(model.simulate(skus, sales, [prices[sku] for sku in skus],
                                                   model.fixed_targets(levels), capacity, *rates).cost.sum())
                      for policy, levels in targets.items()}


def published_bridge(config: Config, source: pd.DataFrame) -> pd.DataFrame:
    """Rerun the originally published design and add the corrections one at a time.

    The original design: one sheet, every calendar week, the last `holdout_weeks` weeks
    held out and all earlier weeks used for training, prices over the whole sheet,
    SKUs active in at least `min_active_weeks` training weeks ranked by training units
    times price, capacity = floor(share x the sum of the NumPy 'higher' critical-ratio
    quantiles), and fixed weekly targets. Each row reselects the cohort and recomputes
    capacity under the rules in force at that step. Removals follow the study's timing:
    training sales as known when the holdout starts, each holdout week as known at its close.
    """
    rates = (config.primary.holding_rate, config.primary.shortage_rate)
    ledger = data.classify(source.loc[source["sheet"].eq(config.bridge_sheet)],
                           window=pd.Timedelta(config.reversal_hours, "h"))
    calendar = data.calendar(ledger)
    rows, applied, previous, panels = [], set(), None, {}
    for step in config.bridge_steps:
        applied.add(step)
        rules = data.DataRules("prompt" if "prompt_reversals" in applied else "none",
                               "code_registry" in applied, "case_normalization" in applied)
        if rules not in panels:
            panels[rules] = data.SalesPanel(ledger, rules, config.country)
        panel = panels[rules]
        weeks = pd.DatetimeIndex(calendar.loc[calendar["complete"] | ("complete_weeks" not in applied), "week_start"])
        train, holdout = weeks[:-config.bridge_holdout_weeks], weeks[-config.bridge_holdout_weeks:]
        start = holdout[0]
        history = panel.matrix(start).loc[train]
        price = (panel.prices(train[0], start, cutoff=start) if "training_prices" in applied else panel.prices())
        table = pd.DataFrame({"active": history.gt(0).sum(), "proxy": history.sum() * price})
        table = table.loc[table["active"].ge(config.bridge_min_active_weeks) & table["proxy"].notna()]
        table = table.rename_axis("sku").reset_index().sort_values(["proxy", "sku"], ascending=[False, True])
        skus = list(table["sku"].head(config.bridge_skus))
        sales = np.vstack([panel.matrix(week + WEEK, skus=skus).loc[week].to_numpy() for week in holdout])
        capacity, costs = fixed_design({sku: history[sku].tolist() for sku in skus}, sales,
                                       {sku: float(price[sku]) for sku in skus}, rates, config.bridge_capacity_share,
                                       "inverse_ecdf_capacity" in applied)
        rows.append({
            "step": step, "label": BRIDGE_STEPS[step].format(hours=config.reversal_hours),
            "train_weeks": len(train), "holdout_weeks": len(holdout),
            "first_holdout_week": start, "capacity_units": capacity, "skus": len(skus),
            "skus_added": " ".join(sorted(set(skus) - set(previous or skus))),
            "skus_removed": " ".join(sorted(set(previous or skus) - set(skus))),
            **{f"{policy}_cost": cost for policy, cost in costs.items()},
            "optimizer_vs_proportional": float(relative(costs["optimizer"], costs["proportional"])),
            "optimizer_vs_scaled_fractile": float(relative(costs["optimizer"], costs["scaled_fractile"])),
            "cohort": " ".join(skus),
        })
        previous = skus
    return pd.DataFrame(rows)


def data_tables(study: Study) -> dict:
    """The data report's tables, for the configured country unless noted."""
    ledger, country = study.ledger, study.config.country
    panel, cohort = study.panel(study.config.primary.rules), list(study.cohort)
    weeks = study.selection.append(study.evaluation)
    stages = data.bridge(ledger, country)
    lines = panel.window(weeks[0], weeks[-1] + WEEK)
    lines = lines.loc[lines["sku"].isin(cohort)]
    stages.loc[len(stages)] = {"stage": "study_cohort", "rows": len(lines), "units": int(lines["quantity"].sum()),
                               "value": float((lines["quantity"] * lines["price"]).sum())}
    final = panel.matrix(None, skus=cohort).loc[weeks]
    revenue = panel.weekly(None)
    revenue = revenue.loc[revenue["sku"].isin(cohort)].set_index(["week_start", "sku"])["revenue"]
    known = pd.DataFrame([panel.matrix(week + WEEK, skus=cohort).loc[week] for week in weeks], index=weeks)
    sales = final.stack().rename("units").reset_index()
    sales["units_at_week_close"] = known.stack().to_numpy()
    sales["revenue"] = revenue.reindex(pd.MultiIndex.from_frame(sales[["week_start", "sku"]])).fillna(0.0).to_numpy()
    sales.insert(1, "period", np.where(sales["week_start"].isin(study.selection), "selection", "evaluation"))
    sales.insert(2, "closure", sales["week_start"].isin(study.closures))
    selection = study.selection_table.copy()
    selection.insert(1, "description", panel.descriptions(study.selection[0], study.evaluation[0], cohort).to_numpy())
    return {
        "selection": selection,
        "reconciliation": data.reconciliation(ledger),
        "stages": stages,
        "pairs": data.reversal_pairs(ledger),
        "credits": data.credit_summary(ledger, country),
        "registry": data.registry_exclusions(ledger, country),
        "unusual": panel.unusual_codes(weeks[0], weeks[-1] + WEEK),
        "aliases": panel.aliases(cohort),
        "drift": panel.description_drift(cohort),
        "concentration": panel.concentration(weeks[0], weeks[-1] + WEEK, skus=cohort).reset_index(),
        "repeated": data.repeated_lines(ledger),
        "weekly_sales": sales,
    }


@dataclass(frozen=True)
class Result:
    config: Config
    study: Study
    sheets: dict
    scenarios: tuple  # ScenarioResult, primary first
    forecasts: pd.DataFrame
    decisions: pd.DataFrame
    bridge: pd.DataFrame
    largest: dict
    tables: dict

    @property
    def primary(self) -> ScenarioResult:
        return self.scenarios[0]


def run(config: Config, source: pd.DataFrame) -> Result:
    """Everything the reports need, from the source rows of both sheets."""
    ledger = data.classify(source, window=pd.Timedelta(config.reversal_hours, "h"))
    study = Study(config, ledger)
    blocks = (config.block_weeks,) + config.check_block_weeks
    scenarios = [run_scenario(study, config.primary, blocks)]
    scenarios += [run_scenario(study, scenario) for scenario in config.sensitivities]
    counts = source.groupby("sheet").size()
    sheets = {"rows": {str(sheet): int(rows) for sheet, rows in counts.items()},
              "overlap_rows": int(source["overlap"].sum()), "combined_rows": int((~source["overlap"]).sum())}
    return Result(config, study, sheets, tuple(scenarios), forecast_metrics(study, config.primary),
                  next_targets(study, config.primary), published_bridge(config, source),
                  largest_week(study, config.primary), data_tables(study))
