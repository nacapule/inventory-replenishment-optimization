"""Tests for the configuration, the weekly study, the comparisons and the bridge from the
originally published design."""

import json
import math
import sys
import tomllib
import unittest
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from statistics import median

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synthetic  # noqa: E402
from synthetic import ROOT  # noqa: E402

import data  # noqa: E402
import experiment  # noqa: E402
import model  # noqa: E402

WORKBOOK = ROOT / "data" / "raw" / "online_retail_II.xlsx"
PUBLISHED = ROOT / "configs" / "published.toml"
FIXTURE = ROOT / "tests" / "fixtures" / "model" / "published_run.json"
WEEK = pd.Timedelta(7, "D")


def raw():
    return tomllib.loads(synthetic.config_text())


class ConfigTests(unittest.TestCase):
    def test_published_configuration_declares_one_change_per_sensitivity(self):
        config = experiment.load_config(PUBLISHED)
        self.assertEqual(len(config.sensitivities), 11)
        self.assertEqual((config.primary.holding_rate, config.primary.shortage_rate), (Fraction(1, 20), Fraction(3, 10)))
        self.assertEqual(config.primary.critical_ratio, Fraction(6, 7))
        settings = ("rules", "window", "closures", "capacity_factor", "holding_rate", "shortage_rate", "bulk_cap")
        for scenario in config.sensitivities:
            changed = [name for name in settings if getattr(scenario, name) != getattr(config.primary, name)]
            self.assertEqual(len(changed), 1, scenario.id)
        ratios = {s.id: (s.critical_ratio, s.holding_rate, s.shortage_rate) for s in config.sensitivities}
        self.assertEqual(ratios["ratio_0.95"], (Fraction(19, 20), Fraction(1, 20), Fraction(19, 20)))
        self.assertEqual(ratios["ratio_0.98"][0], Fraction(49, 50))
        self.assertEqual(ratios["ratio_0.75"][2], Fraction(3, 20))

    def test_invalid_values_are_rejected(self):
        cases = [
            ("cohort", "skus", 0), ("cohort", "skus", -1), ("cohort", "skus", True), ("cohort", "skus", 2.0),
            ("cohort", "selection_weeks", 0), ("cohort", "min_active_weeks", 53),
            ("primary", "holding_rate", -0.05), ("primary", "shortage_rate", math.nan),
            ("primary", "holding_rate", math.inf), ("primary", "capacity_factor", -1.0),
            ("primary", "capacity_factor", math.nan), ("primary", "capacity_factor", "1"),
            ("primary", "window", "trailing_8"), ("primary", "closure_weeks", "skip"),
            ("comparison", "policy", "best"), ("comparison", "baselines", ["scaled", "proportional"]),
            ("comparison", "baselines", []), ("bootstrap", "resamples", 0), ("bootstrap", "confidence", 1.0),
            ("bootstrap", "block_weeks", 60), ("bridge", "steps", ["prompt_reversals"]),
            ("bridge", "sheet", "Sheet1"), ("input", "sha256", "abc"),
        ]
        for table, key, value in cases:
            config = raw()
            config[table][key] = value
            with self.subTest(table=table, key=key, value=value), self.assertRaises(experiment.ConfigError):
                experiment.parse_config(config)

    def test_both_rates_zero_is_rejected_but_one_zero_is_valid(self):
        config = raw()
        config["primary"]["holding_rate"] = config["primary"]["shortage_rate"] = 0.0
        with self.assertRaises(experiment.ConfigError):
            experiment.parse_config(config)
        config["primary"]["holding_rate"] = 0.05
        self.assertEqual(experiment.parse_config(config).primary.critical_ratio, 0)

    def test_unknown_keys_bad_sensitivities_and_duplicate_ids_are_rejected(self):
        changes = [
            lambda c: c["primary"].update(holdingrate=0.1),
            lambda c: c.update(extra={}),
            lambda c: c["sensitivity"][0].update(critical_ratio=1.0),
            lambda c: c["sensitivity"][0].update(critical_ratio=0),
            lambda c: c["sensitivity"][1].update(data={"reversals": "some"}),
            lambda c: c["sensitivity"][1].update(data={"registry": "yes"}),
            lambda c: c["sensitivity"][2].update(bulk_cap_quantile=0),
            lambda c: c["sensitivity"][2].update(id="primary"),
            lambda c: c["sensitivity"][2].pop("label"),
        ]
        for number, change in enumerate(changes):
            config = raw()
            change(config)
            with self.subTest(number), self.assertRaises(experiment.ConfigError):
                experiment.parse_config(config)

    def test_rates_are_read_as_written(self):
        config = raw()
        config["primary"]["holding_rate"], config["primary"]["shortage_rate"] = 0.1, 0.2
        primary = experiment.parse_config(config).primary
        self.assertEqual((primary.holding_rate, primary.shortage_rate), (Fraction(1, 10), Fraction(1, 5)))

    def test_capacity_rounds_halves_up_exactly(self):
        self.assertEqual(experiment.capacity_units(Fraction(3, 4), Fraction(10)), 8)
        self.assertEqual(experiment.capacity_units(Fraction(1), Fraction(109740, 17)), 6455)
        self.assertEqual(experiment.capacity_units(Fraction(0), Fraction(109740, 17)), 0)


def weekly_oracle(rows, codes, start, end):
    """Units per (Monday, code) from raw lines with every planted reversal pair removed."""
    frame = pd.DataFrame(rows)
    frame = frame.loc[~frame["invoice"].isin(["900001", "C900002", "900003", "C900004"])]
    frame = frame.loc[~frame["invoice"].str.startswith("C")]
    frame["sku"] = frame["stock_code"].str.upper()
    frame = frame.loc[frame["sku"].isin(codes) & frame["timestamp"].ge(start) & frame["timestamp"].lt(end)]
    monday = frame["timestamp"].dt.normalize() - pd.to_timedelta(frame["timestamp"].dt.weekday, unit="D")
    return frame.assign(week=monday)


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.study = synthetic.study()

    def test_selection_and_evaluation_use_complete_weeks_only(self):
        study = self.study
        weeks = study.calendar.set_index("week_start")
        self.assertTrue(weeks.loc[study.selection, "complete"].all() and weeks.loc[study.evaluation, "complete"].all())
        self.assertEqual(study.selection[0], pd.Timestamp("2009-12-07"))  # the week of 30 November is partial
        self.assertEqual(study.evaluation[-1], pd.Timestamp("2011-11-28"))  # the week of 5 December is partial
        self.assertEqual((len(study.selection), len(study.evaluation)), (52, 52))
        self.assertTrue((np.diff(study.selection.append(study.evaluation)) == WEEK).all())
        self.assertEqual(list(study.closures), list(synthetic.CLOSED))

    def test_cohort_is_ranked_by_selection_year_revenue_among_active_products(self):
        study = self.study
        lines = weekly_oracle(synthetic.lines(), list(synthetic.PRODUCTS), study.selection[0],
                              study.selection[-1] + WEEK)
        revenue = (lines["quantity"] * lines["price"]).groupby(lines["sku"]).sum()
        active = lines.groupby("sku")["week"].nunique()
        expected = revenue[active >= 20].sort_values(ascending=False).index[:4]
        self.assertEqual(study.cohort, tuple(expected))
        self.assertNotIn("DOT", study.cohort)
        units = lines.loc[lines["sku"].isin(expected), "quantity"].sum()
        self.assertEqual(study.mean_units, Fraction(int(units), 51))

    def test_capacity_does_not_change_with_cost_rates(self):
        study, primary = self.study, synthetic.config().primary
        expected = experiment.capacity_units(Fraction(1), study.mean_units)
        for holding, shortage in [("0.01", "0.3"), ("0.05", "0.3"), ("0.2", "0.3"), ("0.05", "0.95")]:
            scenario = replace(primary, holding_rate=Fraction(holding), shortage_rate=Fraction(shortage))
            with self.subTest(holding=holding, shortage=shortage):
                self.assertEqual(experiment.run_scenario(study, scenario).capacity, expected)

    def test_zero_capacity_factor_gives_zero_stock_within_the_limit(self):
        result = experiment.run_scenario(self.study, replace(synthetic.config().primary, capacity_factor=Fraction(0)))
        self.assertEqual(result.capacity, 0)
        for policy, run in result.runs.items():
            self.assertEqual(int(run.start.sum()) == 0, policy != "unconstrained", policy)

    def test_history_windows_and_closure_weeks(self):
        t = pd.Timestamp("2011-01-03")
        weeks = lambda start, count: pd.date_range(start, periods=count, freq="7D")  # noqa: E731
        trailing = weeks("2010-01-04", 52)
        cases = {
            ("trailing_52", "drop"): trailing.drop(pd.Timestamp("2010-12-27")),
            ("trailing_52", "zero"): trailing,
            ("trailing_13", "drop"): weeks("2010-10-04", 13).drop(pd.Timestamp("2010-12-27")),
            ("seasonal_analog", "drop"): weeks("2010-01-04", 13),
        }
        for (window, closures), expected in cases.items():
            with self.subTest(window=window, closures=closures):
                self.assertEqual(list(self.study.history_weeks(t, window, closures)), list(expected))

    def test_prices_use_only_lines_before_the_decision_week(self):
        rows = pd.DataFrame(synthetic.lines())
        rows = rows.loc[rows["stock_code"].eq("10003") & ~rows["invoice"].str.startswith("C")]
        for t in self.study.evaluation:
            inside = rows.loc[rows["timestamp"].ge(t - 52 * WEEK) & rows["timestamp"].lt(t)]
            # the reversed sale leaves the window once its credit is known
            inside = inside.loc[~(inside["invoice"].eq("900003") & (t > pd.Timestamp("2011-02-14 00:10")))]
            with self.subTest(week=t.date()):
                self.assertEqual(self.study.prices(data.PRIMARY_RULES, t)["10003"], median(inside["price"]))
        self.assertEqual(self.study.prices(data.PRIMARY_RULES, pd.Timestamp("2011-06-06"))["10003"], 9.0)
        self.assertEqual(self.study.prices(data.PRIMARY_RULES, pd.Timestamp("2011-11-28"))["10003"], 10.0)

    def test_scored_sales_apply_only_reversals_known_by_the_week_end(self):
        study, rules = self.study, data.PRIMARY_RULES
        scored = pd.DataFrame(study.scored_sales(rules), index=study.evaluation, columns=study.cohort)
        final = study.matrix(rules, None)
        sunday_sale_week, prompt_week = pd.Timestamp("2011-02-07"), pd.Timestamp("2011-03-14")
        self.assertEqual(scored.at[sunday_sale_week, "10003"] - final.at[sunday_sale_week, "10003"], 30)
        self.assertEqual(scored.at[prompt_week, "10001"], final.at[prompt_week, "10001"])
        lines = weekly_oracle(synthetic.lines(), list(study.cohort), study.evaluation[0], study.evaluation[-1] + WEEK)
        oracle = lines.groupby(["week", "sku"])["quantity"].sum().unstack(fill_value=0)
        oracle = oracle.reindex(index=study.evaluation, columns=list(study.cohort), fill_value=0)
        oracle.loc[sunday_sale_week, "10003"] += 30
        self.assertTrue((scored.to_numpy() == oracle.to_numpy()).all())

    def test_decisions_do_not_look_ahead(self):
        k = 10
        t = self.study.evaluation[k]
        sale = synthetic.line(910001, "10002", 77, t - pd.Timedelta(20, "min"), 2.5, 12348)
        base = synthetic.lines() + [sale]
        changed = []
        for row in base:
            row = dict(row)
            if row["timestamp"] >= t:
                row["quantity"] *= 3
                row["price"] += 1.0
            changed.append(row)
        changed.append(synthetic.line("C910002", "10002", -77, t + pd.Timedelta(10, "min"), 2.5, 12348))
        config = synthetic.config()
        studies = [experiment.Study(config, data.classify(synthetic.source(rows))) for rows in (base, changed)]
        before, after = (experiment.run_scenario(study, config.primary) for study in studies)
        self.assertEqual(studies[0].cohort, studies[1].cohort)
        self.assertEqual(studies[0].mean_units, studies[1].mean_units)
        self.assertEqual(before.capacity, after.capacity)
        self.assertTrue((before.prices[:k + 1] == after.prices[:k + 1]).all())
        for policy in experiment.POLICIES:
            with self.subTest(policy=policy):
                first, second = before.runs[policy], after.runs[policy]
                self.assertTrue((first.start[:k + 1] == second.start[:k + 1]).all())
                self.assertTrue((first.sales[:k] == second.sales[:k]).all())
        self.assertFalse((before.runs["optimizer"].sales[k:] == after.runs["optimizer"].sales[k:]).all())
        self.assertFalse((before.prices[k + 1:] == after.prices[k + 1:]).all())


class PolicyTests(unittest.TestCase):
    def test_policies_keep_carried_stock_and_the_limit(self):
        study = synthetic.study()
        primary = synthetic.config().primary
        plan = study.plan(primary, study.evaluation[20])
        h, p = primary.holding_rate, primary.shortage_rate
        targets = model.newsvendor_targets(plan.histories, h, p)
        carried = {sku: 40 for sku in study.cohort}
        capacity = experiment.capacity_units(Fraction(1, 2), study.mean_units)
        stock = {policy: experiment.decide(policy, plan, targets, carried, capacity, h, p)
                 for policy in experiment.POLICIES}
        for policy, levels in stock.items():
            with self.subTest(policy=policy):
                self.assertTrue(all(levels[sku] >= carried[sku] for sku in study.cohort))
                if policy != "unconstrained":
                    self.assertLessEqual(sum(levels.values()), capacity)
        self.assertEqual(stock["unconstrained"], {sku: max(targets[sku], 40) for sku in study.cohort})
        cheap = {sku: 1.0 for sku in study.cohort}
        repriced = replace(plan, prices=cheap)
        self.assertEqual(experiment.decide("optimizer_unit", repriced, targets, carried, capacity, h, p),
                         stock["optimizer_unit"])
        self.assertEqual(plan.means, {sku: Fraction(sum(v), len(v)) for sku, v in plan.histories.items()})

    def test_proportional_targets_follow_the_window_means(self):
        study = synthetic.study()
        primary = synthetic.config().primary
        plan = study.plan(primary, study.evaluation[0])
        capacity = experiment.capacity_units(Fraction(1), study.mean_units)
        zero = {sku: 0 for sku in study.cohort}
        levels = experiment.decide("proportional", plan, {}, zero, capacity, primary.holding_rate,
                                   primary.shortage_rate)
        self.assertEqual(sum(levels.values()), capacity)
        total = sum(plan.means.values())
        for sku in study.cohort:
            self.assertLess(abs(levels[sku] - capacity * plan.means[sku] / total), 1)

    def test_runs_start_empty_and_constrained_policies_stay_within_the_limit(self):
        result = synthetic.result().primary
        for policy, run in result.runs.items():
            with self.subTest(policy=policy):
                self.assertEqual(int(run.opening[0].sum()), 0)
                within = int(run.start.sum(axis=1).max()) <= result.capacity
                self.assertTrue(within or policy == "unconstrained")


class ComparisonTests(unittest.TestCase):
    def test_moving_blocks_are_consecutive_weeks_and_reproducible(self):
        positions = experiment.block_indices(10, 4, 50, seed=3)
        self.assertEqual(positions.shape, (50, 10))
        self.assertTrue(((positions >= 0) & (positions < 10)).all())
        for row in positions:
            for start in range(0, 10, 4):
                block = row[start:start + 4]
                self.assertTrue((np.diff(block) == 1).all())
        self.assertTrue((experiment.block_indices(10, 4, 50, seed=3) == positions).all())
        self.assertFalse((experiment.block_indices(10, 2, 50, seed=3) == positions).all())

    def test_interval_of_a_constant_difference_is_that_difference(self):
        weeks = 13
        base, policy = np.full(weeks, 100.0), np.full(weeks, 104.0)
        samples = {4: experiment.block_indices(weeks, 4, 200, seed=1)}
        result = experiment.compare(policy, base, samples, Fraction(19, 20))
        self.assertAlmostEqual(result["relative"], 0.04)
        self.assertEqual(result["intervals"][4]["difference"], [52.0, 52.0])
        self.assertTrue(np.allclose(result["intervals"][4]["relative"], [0.04, 0.04]))
        self.assertEqual((result["weeks_won"], result["weeks_lost"], result["weeks_tied"]), (0, 13, 0))

    def test_interval_matches_a_direct_resampling_loop(self):
        rng = np.random.default_rng(5)
        policy, base = rng.uniform(80, 120, 20), rng.uniform(80, 120, 20)
        positions = experiment.block_indices(20, 4, 400, seed=9)
        result = experiment.compare(policy, base, {4: positions}, Fraction(9, 10))
        totals = sorted(sum(policy[i] for i in row) / sum(base[i] for i in row) - 1 for row in positions)
        low, high = np.quantile(totals, [0.05, 0.95])
        self.assertTrue(np.allclose(result["intervals"][4]["relative"], [low, high]))
        self.assertEqual(result["weeks_won"] + result["weeks_lost"] + result["weeks_tied"], 20)
        self.assertEqual(result["weeks_won"], int(sum(a < b for a, b in zip(policy, base))))

    def test_quarters_and_products_add_up_to_the_totals(self):
        result = synthetic.result().primary
        quarters = experiment.quarters(result)
        products = experiment.sku_contributions(result)
        self.assertEqual(int(quarters["weeks"].sum()), len(result.weeks))
        for policy, run in result.runs.items():
            self.assertAlmostEqual(quarters[policy].sum(), run.cost.sum(), places=6)
            self.assertAlmostEqual(products[f"{policy}_cost"].sum(), run.cost.sum(), places=6)


class ForecastTests(unittest.TestCase):
    def test_metrics_follow_their_definitions(self):
        result, study = synthetic.result(), synthetic.study()
        primary = synthetic.config().primary
        actual = result.primary.runs["optimizer"].sales
        ratio = 6 / 7
        for window in experiment.WINDOWS:
            plans = [study.plan(replace(primary, window=window), t) for t in study.evaluation]
            errors, absolute, pinball = 0.0, 0.0, 0.0
            for week, plan in enumerate(plans):
                for column, sku in enumerate(study.cohort):
                    history, sales = sorted(plan.histories[sku]), int(actual[week, column])
                    estimate = sum(history) / len(history)
                    quantile = next(v for v in history if sum(x <= v for x in history) >= ratio * len(history))
                    errors += estimate - sales
                    absolute += abs(estimate - sales)
                    pinball += ratio * max(sales - quantile, 0) + (1 - ratio) * max(quantile - sales, 0)
            row = result.forecasts.set_index("window").loc[window]
            cells = actual.size
            with self.subTest(window=window):
                self.assertAlmostEqual(row["wape"], absolute / actual.sum())
                self.assertAlmostEqual(row["bias"], errors / actual.sum())
                self.assertAlmostEqual(row["mae"], absolute / cells)
                self.assertAlmostEqual(row["pinball_loss"], pinball / cells)


class BridgeTests(unittest.TestCase):
    def test_original_design_reproduces_the_published_costs(self):
        run = json.loads(FIXTURE.read_text())
        training = np.array(run["training_units"])
        histories = {sku: training[:, i].tolist() for i, sku in enumerate(run["skus"])}
        prices = dict(zip(run["skus"], run["unit_price"]))
        rates = (run["holding_rate"], run["shortage_rate"])
        capacity, costs = experiment.fixed_design(histories, np.array(run["holdout_units"]), prices, rates,
                                                  Fraction(85, 100), smallest_optimum=False)
        self.assertEqual(capacity, 7060)
        self.assertEqual(round(costs["optimizer"], 2), 24208.82)
        self.assertEqual(round(costs["proportional"], 2), 27971.87)
        self.assertEqual(round(costs["scaled_fractile"], 2), 23352.26)
        smaller, _ = experiment.fixed_design(histories, np.array(run["holdout_units"]), prices, rates,
                                             Fraction(85, 100), smallest_optimum=True)
        self.assertEqual(smaller, math.floor(Fraction(85, 100) * 7699))

    def test_each_step_adds_one_correction(self):
        bridge = synthetic.result().bridge
        self.assertEqual(list(bridge["step"]), list(experiment.BRIDGE_STEPS))
        complete = bridge["step"].isin(["complete_weeks", "training_prices", "inverse_ecdf_capacity"])
        self.assertTrue((bridge.loc[~complete, ["train_weeks", "holdout_weeks"]] == [42, 12]).all().all())
        self.assertTrue((bridge.loc[complete, ["train_weeks", "holdout_weeks"]] == [40, 12]).all().all())
        self.assertEqual(list(bridge["first_holdout_week"].iloc[[0, 4]]),
                         [pd.Timestamp("2011-09-19"), pd.Timestamp("2011-09-12")])
        cohorts = [set(cohort.split()) for cohort in bridge["cohort"]]
        for number in range(1, len(bridge)):
            added = set(bridge["skus_added"].iloc[number].split())
            removed = set(bridge["skus_removed"].iloc[number].split())
            self.assertEqual(cohorts[number], (cohorts[number - 1] - removed) | added)
        self.assertNotIn("DOT", cohorts[-1])
        self.assertTrue(np.allclose(bridge["optimizer_vs_proportional"],
                                    bridge["optimizer_cost"] / bridge["proportional_cost"] - 1))


@unittest.skipUnless(WORKBOOK.exists(), "the Online Retail II workbook is not in data/raw")
class RealWorkbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = experiment.load_config(PUBLISHED)
        cls.bridge = experiment.published_bridge(cls.config, data.read_workbook(WORKBOOK)).set_index("step")

    def test_bridge_starts_from_the_published_comparison(self):
        first = self.bridge.loc["original"]
        self.assertEqual(first["capacity_units"], 7060)
        self.assertEqual(round(first["optimizer_cost"], 2), 24208.82)
        self.assertEqual(round(first["proportional_cost"], 2), 27971.87)
        self.assertEqual(first["cohort"].split(), json.loads(FIXTURE.read_text())["skus"])

    def test_removing_prompt_reversals_reselects_and_resizes(self):
        row = self.bridge.loc["prompt_reversals"]
        self.assertEqual((row["capacity_units"], row["skus_added"], row["skus_removed"]), (7032, "20685", "23166"))
        self.assertEqual(round(row["optimizer_cost"], 2), 24113.00)
        self.assertEqual(round(row["proportional_cost"], 2), 23821.61)


if __name__ == "__main__":
    unittest.main()
