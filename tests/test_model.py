"""Tests for the newsvendor allocation and the weekly stock simulation.

Expected costs and optima are checked against plain loops and exhaustive enumeration
written here with exact fractions, never against the module's own cost functions.
"""

import heapq
import itertools
import json
import math
import random
import sys
import unittest
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import model  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "model" / "published_run.json"


# Independent references -----------------------------------------------------------------


def loop_cost(samples, quantity, holding, shortage):
    """Mean holding * leftover + shortage * unmet, one sample at a time, exactly."""
    total = Fraction(0)
    for sale in samples:
        if quantity >= sale:
            total += holding * (quantity - sale)
        else:
            total += shortage * (sale - quantity)
    return total / len(samples)


def cost_table(histories, prices, holding, shortage, floors):
    """Each SKU's price-weighted expected cost for every stock level worth trying."""
    table = {}
    for sku, samples in histories.items():
        top = max(floors[sku], max(samples))
        table[sku] = {
            level: Fraction(prices[sku]) * loop_cost(samples, level, holding, shortage)
            for level in range(floors[sku], top + 1)
        }
    return table


def enumerate_minimum(histories, prices, holding, shortage, capacity, floors):
    """The least total cost over every allocation at or above the floors within capacity.
    Levels above the largest sample never cost less, so the search stops there."""
    table = cost_table(histories, prices, holding, shortage, floors)
    skus = list(histories)
    best = None
    for levels in itertools.product(*(sorted(table[sku]) for sku in skus)):
        if capacity is not None and sum(levels) > capacity:
            continue
        cost = sum(table[sku][level] for sku, level in zip(skus, levels))
        if best is None or cost < best:
            best = cost
    return best


def unit_by_unit(histories, prices, holding, shortage, capacity, floors):
    """Add one unit at a time to the most negative exact marginal (equal marginals to the
    SKU that sorts first) until capacity runs out or no marginal is negative."""
    allocation = dict(floors)

    def marginal(sku):
        samples = histories[sku]
        below = sum(1 for sale in samples if sale <= allocation[sku])
        return Fraction(prices[sku]) * ((holding + shortage) * Fraction(below, len(samples)) - shortage)

    free = None if capacity is None else capacity - sum(floors.values())
    heap = [(marginal(sku), sku) for sku in histories]
    heapq.heapify(heap)
    while heap and (free is None or free > 0):
        delta, sku = heapq.heappop(heap)
        if delta >= 0:
            break
        allocation[sku] += 1
        if free is not None:
            free -= 1
        heapq.heappush(heap, (marginal(sku), sku))
    return allocation


def largest_remainder(weights, capacity):
    """Hamilton apportionment with exact quotas; equal remainders follow mapping order."""
    keys = list(weights)
    total = sum(Fraction(weights[key]) for key in keys)
    if total == 0 or capacity == 0:
        return {key: 0 for key in keys}
    quotas = {key: capacity * Fraction(weights[key]) / total for key in keys}
    result = {key: math.floor(quotas[key]) for key in keys}
    ranked = sorted(range(len(keys)), key=lambda i: -(quotas[keys[i]] - result[keys[i]]))
    for index in ranked[: capacity - sum(result.values())]:
        result[keys[index]] += 1
    return result


def broadcast_costs(sales, targets, prices, holding, shortage):
    """The original evaluator: one stock vector scored against every week's sales."""
    sales = np.asarray(sales, dtype=float)
    stock = np.broadcast_to(np.asarray(targets, dtype=float), sales.shape)
    price = np.broadcast_to(np.asarray(prices, dtype=float), sales.shape)
    leftover = np.maximum(stock - sales, 0.0)
    unmet = np.maximum(sales - stock, 0.0)
    return leftover * price * holding, unmet * price * shortage


def load_published_run():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    skus = data["skus"]
    training = np.array(data["training_units"])
    data["histories"] = {sku: training[:, i] for i, sku in enumerate(skus)}
    data["prices"] = dict(zip(skus, data["unit_price"]))
    for column in ("optimized_qty", "proportional_qty", "newsvendor_qty"):
        data[column] = dict(zip(skus, data[column]))
    return data


RATE_PAIRS = [
    (Fraction(1, 20), Fraction(3, 10)),
    (Fraction(1), Fraction(3, 2)),
    (Fraction(1), Fraction(3)),
    (Fraction(2), Fraction(1)),
    (Fraction(1, 20), Fraction(19, 20)),
    (Fraction(0), Fraction(1)),
    (Fraction(1), Fraction(0)),
]
PRICES = [0.1, 0.3, 0.5, 1.0, 1.5, 2.0, 3.0, 12.75, 185.47]


def seeded_cases(count, seed=20261006):
    rng = random.Random(seed)
    for _ in range(count):
        skus = ["A", "B", "C"][: rng.choice([2, 3])]
        histories = {sku: [rng.randint(0, 5) for _ in range(rng.randint(1, 6))] for sku in skus}
        prices = {sku: rng.choice(PRICES) for sku in skus}
        holding, shortage = rng.choice(RATE_PAIRS)
        capacity = rng.choice([None, 0, 1, 2, 3, 4, 5, 6, 8, 10, 20])
        floors = {sku: 0 for sku in skus}
        if rng.random() < 0.5:
            floors = {sku: rng.randint(0, 3) for sku in skus}
            if capacity is not None and sum(floors.values()) > capacity:
                floors = {sku: 0 for sku in skus}
        yield histories, prices, holding, shortage, capacity, floors


# Costs ----------------------------------------------------------------------------------


class CostTests(unittest.TestCase):
    def test_expected_cost_balances_overage_and_underage(self):
        self.assertAlmostEqual(model.expected_cost([0, 2, 4], 2, holding=1.0, shortage=3.0), 8 / 3)

    def test_expected_and_marginal_cost_match_loops(self):
        rng = random.Random(7)
        for _ in range(300):
            samples = [rng.randint(0, 9) for _ in range(rng.randint(1, 8))]
            holding, shortage = rng.choice(RATE_PAIRS)
            level = rng.randint(0, 11)
            exact = loop_cost(samples, level, holding, shortage)
            step = loop_cost(samples, level + 1, holding, shortage) - exact
            self.assertAlmostEqual(model.expected_cost(samples, level, holding, shortage), float(exact))
            self.assertAlmostEqual(model.marginal_cost(samples, level, holding, shortage), float(step))

    def test_critical_ratio_is_exact_from_configured_decimals(self):
        self.assertEqual(model.critical_ratio("0.05", "0.30"), Fraction(6, 7))
        self.assertEqual(model.critical_ratio(0.05, 0.30), Fraction(6, 7))
        self.assertEqual(model.critical_ratio(Fraction(1, 20), Fraction(19, 20)), Fraction(19, 20))
        with self.assertRaises(ValueError):
            model.critical_ratio(0, 0)


# Allocation -----------------------------------------------------------------------------


class AllocationTests(unittest.TestCase):
    def test_optimizer_matches_brute_force(self):
        histories = {"A": [0, 1, 2, 3], "B": [0, 0, 2, 5]}
        prices = {"A": 1.0, "B": 1.5}
        floors = {"A": 0, "B": 0}
        allocation = model.optimize_capacity(histories, prices, 1, 4, 4)
        table = cost_table(histories, prices, Fraction(1), Fraction(4), floors)
        cost = sum(table[sku][allocation[sku]] for sku in histories)
        self.assertEqual(cost, enumerate_minimum(histories, prices, Fraction(1), Fraction(4), 4, floors))
        self.assertLessEqual(sum(allocation.values()), 4)

    def test_exhaustive_enumeration_on_seeded_cases(self):
        checked = 0
        for histories, prices, holding, shortage, capacity, floors in seeded_cases(1500):
            with self.subTest(histories=histories, prices=prices, rates=(holding, shortage),
                              capacity=capacity, floors=floors):
                got = model.optimize_capacity(histories, prices, holding, shortage, capacity, floors)
                for sku in histories:
                    self.assertGreaterEqual(got[sku], floors[sku])
                if capacity is not None:
                    self.assertLessEqual(sum(got.values()), capacity)
                table = cost_table(histories, prices, holding, shortage, floors)
                self.assertTrue(all(got[sku] <= max(table[sku]) for sku in histories))
                cost = sum(table[sku][got[sku]] for sku in histories)
                self.assertEqual(
                    cost, enumerate_minimum(histories, prices, holding, shortage, capacity, floors)
                )
                self.assertEqual(
                    got, unit_by_unit(histories, prices, holding, shortage, capacity, floors)
                )
                if capacity is None:
                    smallest = {
                        sku: min(table[sku], key=lambda level: (table[sku][level], level))
                        for sku in histories
                    }
                    self.assertEqual(got, smallest)
                checked += 1
        self.assertEqual(checked, 1500)

    def test_equal_marginals_go_to_the_sku_that_sorts_first(self):
        histories = {"B": [0, 4], "A": [0, 4]}
        prices = {"B": 2.0, "A": 2.0}
        self.assertEqual(model.optimize_capacity(histories, prices, 1, 3, 5), {"B": 1, "A": 4})
        self.assertEqual(model.optimize_capacity(histories, prices, 1, 3, 8), {"B": 4, "A": 4})

    def test_exact_ties_and_extreme_prices_are_ordered_exactly(self):
        # Equal marginals that floating-point products would round apart.
        histories = {"A": [1, 1, 1], "B": [1]}
        self.assertEqual(
            model.optimize_capacity(histories, {"A": 0.1, "B": 0.1}, 0.05, 0.30, 1), {"A": 1, "B": 0}
        )
        # Prices whose price-weighted marginals would overflow a float.
        prices = {"A": 1e308, "B": 1.5e308}
        self.assertEqual(
            model.optimize_capacity({"A": [1], "B": [1]}, prices, 0.05, 0.30, 1), {"A": 0, "B": 1}
        )

    def test_zero_capacity_keeps_floors(self):
        histories = {"A": [3, 5], "B": [1, 9]}
        self.assertEqual(model.optimize_capacity(histories, None, 1, 3, 0), {"A": 0, "B": 0})
        floors = {"A": 2, "B": 1}
        self.assertEqual(model.optimize_capacity(histories, None, 1, 3, 3, floors), floors)

    def test_unused_capacity_stops_at_the_smallest_optimum(self):
        histories = {"A": [0, 0, 1], "B": [2, 2, 7, 7]}
        got = model.optimize_capacity(histories, {"A": 4.0, "B": 0.5}, 1, Fraction(3, 2), 50)
        self.assertEqual(got, {"A": 0, "B": 7})
        self.assertEqual(got, model.newsvendor_targets(histories, 1, Fraction(3, 2)))

    def test_floors_above_the_optimum_are_kept(self):
        histories = {"A": [1, 1, 1], "B": [5, 6, 7]}
        got = model.optimize_capacity(histories, None, 1, 3, 12, {"A": 4, "B": 0})
        self.assertEqual(got, {"A": 4, "B": 7})
        with self.assertRaises(ValueError):
            model.optimize_capacity(histories, None, 1, 3, 3, {"A": 4, "B": 0})

    def test_one_zero_cost_rate(self):
        histories = {"A": [0, 3, 8], "B": [2]}
        self.assertEqual(model.optimize_capacity(histories, None, 1, 0, None), {"A": 0, "B": 0})
        self.assertEqual(model.optimize_capacity(histories, None, 0, 1, None), {"A": 8, "B": 2})
        self.assertEqual(model.optimize_capacity(histories, None, 0, 1, 5), {"A": 3, "B": 2})

    def test_newsvendor_takes_smallest_optimum_for_0_0_1(self):
        # The upper order statistic picks 1 here (cost 2/3); the optimum is 0 (cost 1/2).
        self.assertEqual(model.newsvendor_targets({"A": [0, 0, 1]}, 1, 1.5), {"A": 0})
        self.assertEqual(model.optimize_capacity({"A": [0, 0, 1]}, {"A": 9.99}, 1, 1.5, None), {"A": 0})
        self.assertEqual(loop_cost([0, 0, 1], 0, 1, Fraction(3, 2)), Fraction(1, 2))
        self.assertEqual(loop_cost([0, 0, 1], 1, 1, Fraction(3, 2)), Fraction(2, 3))

    def test_newsvendor_is_the_inverse_empirical_cdf(self):
        rng = random.Random(11)
        for _ in range(500):
            samples = [rng.randint(0, 30) for _ in range(rng.randint(1, 60))]
            holding, shortage = rng.choice([pair for pair in RATE_PAIRS if pair[1] > 0])
            rank = math.ceil(len(samples) * shortage / (holding + shortage))
            expected = sorted(samples)[rank - 1]
            self.assertEqual(model.newsvendor_targets({"A": samples}, holding, shortage), {"A": expected})

    def test_identical_histories_get_identical_quantities_at_any_price(self):
        for weeks in (36, 42, 49):
            histories = {"A": list(range(weeks)), "B": list(range(weeks))}
            prices = {"A": 185.47, "B": 12.75}
            unconstrained = model.optimize_capacity(histories, prices, 0.05, 0.30, None)
            self.assertEqual(unconstrained["A"], unconstrained["B"])
            self.assertEqual(unconstrained["A"], math.ceil(weeks * 6 / 7) - 1)
            upper = model.upper_quantile_targets(histories, 0.05, 0.30)
            self.assertEqual(upper["A"], upper["B"])
            self.assertEqual(upper["A"], math.ceil(Fraction(6, 7) * (weeks - 1)))

    def test_upper_quantile_matches_numpy_higher_away_from_ties(self):
        rng = random.Random(5)
        for _ in range(300):
            samples = [rng.randint(0, 40) for _ in range(rng.randint(2, 60))]
            ratio = Fraction(6, 7)
            if ((len(samples) - 1) * ratio).denominator == 1:
                continue
            numpy_value = int(np.quantile(samples, float(ratio), method="higher"))
            self.assertEqual(model.upper_quantile_targets({"A": samples}, "0.05", "0.30"), {"A": numpy_value})

    def test_equal_price_diagnostic(self):
        histories = {"A": [0, 4, 9], "B": [1, 2, 3, 8], "C": [5]}
        ones = {sku: 1 for sku in histories}
        self.assertEqual(
            model.optimize_capacity(histories, None, "0.05", "0.30", 9),
            model.optimize_capacity(histories, ones, "0.05", "0.30", 9),
        )

    def test_published_allocations_reproduce(self):
        run = load_published_run()
        rates = run["holding_rate"], run["shortage_rate"]
        optimized = model.optimize_capacity(run["histories"], run["prices"], *rates, run["capacity"])
        self.assertEqual(optimized, run["optimized_qty"])
        means = {sku: float(np.mean(values)) for sku, values in run["histories"].items()}
        self.assertEqual(model.proportional_allocation(means, run["capacity"]), run["proportional_qty"])
        upper = model.upper_quantile_targets(run["histories"], *rates)
        self.assertEqual(upper, run["newsvendor_qty"])
        self.assertEqual(math.floor(0.85 * sum(upper.values())), run["capacity"])
        self.assertEqual(sum(model.newsvendor_targets(run["histories"], *rates).values()), 7699)


class ProportionalTests(unittest.TestCase):
    def test_proportional_allocation_uses_exact_capacity(self):
        allocation = model.proportional_allocation({"A": 4.0, "B": 3.0, "C": 1.0}, 7)
        self.assertEqual(sum(allocation.values()), 7)
        self.assertEqual(allocation, {"A": 3, "B": 3, "C": 1})

    def test_largest_remainder_matches_exact_apportionment(self):
        rng = random.Random(3)
        for _ in range(500):
            weights = {f"S{i}": rng.randint(0, 9) for i in range(rng.randint(1, 6))}
            capacity = rng.randint(0, 40)
            self.assertEqual(model.proportional_allocation(weights, capacity), largest_remainder(weights, capacity))
            means = {key: value / 3 for key, value in weights.items()}
            got = model.proportional_allocation(means, capacity)
            total = sum(Fraction(v) for v in means.values())
            self.assertEqual(sum(got.values()), capacity if total else 0)
            for key, value in means.items():
                quota = capacity * Fraction(value) / total if total else 0
                self.assertLessEqual(abs(got[key] - quota), 1)

    def test_apportionment_is_exact_for_extreme_values(self):
        self.assertEqual(model.proportional_allocation({"A": 1e308, "B": 1e308}, 10), {"A": 5, "B": 5})
        large = 2**54 + 3
        got = model.proportional_allocation({"A": 1.0, "B": 1.0}, large)
        self.assertEqual(got, {"A": 2**53 + 2, "B": 2**53 + 1})
        self.assertEqual(model.proportional_allocation({"A": Decimal("0.1"), "B": Fraction(1, 5)}, 3),
                         {"A": 1, "B": 2})

    def test_scaled_targets_sum_exactly_and_never_inflate(self):
        rng = random.Random(13)
        for _ in range(500):
            targets = {f"S{i}": rng.randint(0, 30) for i in range(rng.randint(1, 6))}
            capacity = rng.randint(0, 120)
            got = model.scale_to_capacity(targets, capacity)
            if sum(targets.values()) <= capacity:
                self.assertEqual(got, targets)
            else:
                self.assertEqual(got, largest_remainder(targets, capacity))
                self.assertEqual(sum(got.values()), capacity)
            self.assertTrue(all(got[key] <= targets[key] for key in targets))
        self.assertEqual(model.scale_to_capacity({"A": 5}, None), {"A": 5})

    def test_gap_filling_sums_exactly_and_respects_floors(self):
        rng = random.Random(17)
        for _ in range(800):
            keys = [f"S{i}" for i in range(rng.randint(1, 6))]
            targets = {key: rng.randint(0, 30) for key in keys}
            floors = {key: rng.randint(0, 20) for key in keys}
            capacity = rng.randint(sum(floors.values()), sum(floors.values()) + 60)
            got = model.fill_gaps(targets, floors, capacity)
            gaps = {key: max(targets[key] - floors[key], 0) for key in keys}
            free = capacity - sum(floors.values())
            added = gaps if sum(gaps.values()) <= free else largest_remainder(gaps, free)
            self.assertEqual(got, {key: floors[key] + added[key] for key in keys})
            self.assertEqual(sum(got.values()), min(capacity, sum(floors.values()) + sum(gaps.values())))
            for key in keys:
                self.assertGreaterEqual(got[key], floors[key])
                self.assertLessEqual(got[key], max(targets[key], floors[key]))
        self.assertEqual(model.fill_gaps({"A": 3, "B": 9}, {"A": 5, "B": 1}, None), {"A": 5, "B": 9})
        with self.assertRaises(ValueError):
            model.fill_gaps({"A": 3}, {"A": 5}, 4)


# Simulation -----------------------------------------------------------------------------


class SimulationTests(unittest.TestCase):
    def test_fixed_targets_match_the_broadcast_evaluator(self):
        rng = np.random.default_rng(23)
        for _ in range(300):
            weeks, count = int(rng.integers(1, 13)), int(rng.integers(1, 5))
            skus = [f"S{i}" for i in range(count)]
            sales = rng.integers(0, 25, size=(weeks, count))
            targets = rng.integers(0, 25, size=count)
            prices = rng.uniform(0.3, 200.0, size=count).round(2)
            capacity = rng.choice([None, int(targets.sum())])
            sim = model.simulate(
                skus, sales, prices, model.fixed_targets(dict(zip(skus, targets.tolist()))),
                capacity, "0.05", "0.30",
            )
            holding, shortage = broadcast_costs(sales, targets, prices, 0.05, 0.30)
            self.assertTrue(np.array_equal(sim.holding_cost, holding))
            self.assertTrue(np.array_equal(sim.shortage_cost, shortage))
            self.assertTrue((sim.start == targets).all())

    def test_published_holdout_costs_reproduce(self):
        run = load_published_run()
        skus, sales, rates = run["skus"], np.array(run["holdout_units"]), (run["holding_rate"], run["shortage_rate"])
        expected = {"optimized_qty": (24208.82, 59113), "proportional_qty": (27971.87, 52298)}
        for column, (published, orders) in expected.items():
            targets = run[column]
            sim = model.simulate(skus, sales, run["unit_price"], model.fixed_targets(targets),
                                 run["capacity"], *rates)
            total = float(sim.cost.sum())
            self.assertEqual(round(total, 2), published)
            holding, shortage = broadcast_costs(sales, [targets[s] for s in skus], run["unit_price"], 0.05, 0.30)
            self.assertAlmostEqual(total, float(holding.sum() + shortage.sum()), places=6)
            self.assertEqual(int(sim.ordered.sum()), orders)
        scaled = model.scale_to_capacity(model.newsvendor_targets(run["histories"], *rates), run["capacity"])
        sim = model.simulate(skus, sales, run["unit_price"], model.fixed_targets(scaled), run["capacity"], *rates)
        self.assertEqual(round(float(sim.cost.sum()), 2), 23352.26)

    def test_falling_target_keeps_carried_stock(self):
        targets = [10, 0]

        def policy(week, carried):
            return {"A": max(targets[week], carried["A"])}

        sim = model.simulate(["A"], [[0], [0]], [1.0], policy, None, "0.05", "0.30")
        self.assertAlmostEqual(float(sim.cost.sum()), 1.00)
        self.assertEqual(sim.start.tolist(), [[10], [10]])
        self.assertEqual(sim.ordered.tolist(), [[10], [0]])
        reset = sum(
            float(sum(part.sum() for part in broadcast_costs([[0]], [target], [1.0], 0.05, 0.30)))
            for target in targets
        )
        self.assertAlmostEqual(reset, 0.50)

    def test_policy_cannot_discard_stock_or_exceed_capacity(self):
        with self.assertRaises(ValueError):
            model.simulate(["A"], [[0], [0]], [1.0], lambda week, carried: [10 - 10 * week], None, 0.05, 0.3)
        with self.assertRaises(ValueError):
            model.simulate(["A", "B"], [[0, 0]], [1.0, 1.0], lambda week, carried: [3, 3], 5, 0.05, 0.3)
        for stock in ([1.5], [-1], [float("nan")]):
            with self.assertRaises(ValueError):
                model.simulate(["A"], [[0]], [1.0], lambda week, carried: stock, None, 0.05, 0.3)
        with self.assertRaises(ValueError):
            model.simulate(["A"], [[0]], [1.0], lambda week, carried: {"B": 1}, None, 0.05, 0.3)

    def test_replanned_policies_keep_stock_balanced_within_capacity(self):
        rng = np.random.default_rng(29)
        skus = ["A", "B", "C", "D"]
        capacity = 60
        sales = rng.integers(0, 30, size=(40, 4))
        prices = rng.uniform(1, 10, size=(40, 4)).round(2)

        def histories(week):
            window = sales[max(0, week - 8):week] if week else sales[:1] * 0
            return {sku: window[:, i].tolist() for i, sku in enumerate(skus)}

        policies = {
            "optimizer": lambda week, carried: model.optimize_capacity(
                histories(week), dict(zip(skus, prices[week])), "0.05", "0.30", capacity, carried),
            "scaled": lambda week, carried: model.fill_gaps(
                model.scale_to_capacity(model.newsvendor_targets(histories(week), "0.05", "0.30"), capacity),
                carried, capacity),
            "proportional": lambda week, carried: model.fill_gaps(
                model.proportional_allocation(
                    {sku: float(np.mean(v)) for sku, v in histories(week).items()}, capacity),
                carried, capacity),
        }
        for name, policy in policies.items():
            with self.subTest(policy=name):
                sim = model.simulate(skus, sales, prices, policy, capacity, "0.05", "0.30")
                self.assertTrue((sim.start.sum(axis=1) <= capacity).all())
                self.assertTrue(np.array_equal(sim.opening + sim.ordered, sim.start))
                self.assertTrue(np.array_equal(sim.covered + sim.lost, sim.sales))
                self.assertTrue(np.array_equal(sim.start - sim.covered, sim.closing))
                self.assertTrue(np.array_equal(sim.opening[1:], sim.closing[:-1]))
                self.assertTrue(np.allclose(sim.holding_cost, sim.closing * prices * 0.05))
                self.assertTrue(np.allclose(sim.shortage_cost, sim.lost * prices * 0.30))

    def test_prices_are_checked_before_broadcasting(self):
        policy = model.fixed_targets({"A": 1})
        with self.assertRaises(ValueError):
            model.simulate(["A"], np.zeros((0, 1), dtype=int), [float("nan")], policy, None, 1, 1)
        for prices in ([True], ["2.0"], [0.0], [float("inf")]):
            with self.subTest(prices=prices), self.assertRaises(ValueError):
                model.simulate(["A"], [[1]], prices, policy, None, 1, 1)

    def test_capacity_check_counts_large_totals_exactly(self):
        count = 1024
        skus = [f"S{i}" for i in range(count)]
        with self.assertRaises(ValueError):
            model.simulate(skus, np.zeros((1, count), dtype=int), np.ones(count),
                           lambda week, carried: [2**53] * count, 0, 1, 1)

    def test_records_are_long_format_week_by_week(self):
        sim = model.simulate(["A", "B"], [[1, 2], [3, 0]], [2.0, 4.0],
                             model.fixed_targets({"A": 2, "B": 1}), 3, "0.05", "0.30")
        records = sim.records()
        self.assertEqual(records["week"].tolist(), [0, 0, 1, 1])
        self.assertEqual(records["sku"].tolist(), ["A", "B", "A", "B"])
        self.assertEqual(records["start"].tolist(), [2, 1, 2, 1])
        self.assertEqual(records["lost"].tolist(), [0, 1, 1, 0])
        self.assertEqual(records["closing"].tolist(), [1, 0, 0, 1])
        self.assertTrue(np.allclose(records["cost"], [0.1, 1.2, 0.6, 0.2]))


# Input checks ---------------------------------------------------------------------------


class ValidationTests(unittest.TestCase):
    def assertRejected(self, function, *args):
        with self.assertRaises(ValueError):
            function(*args)

    def test_fractional_inputs_are_rejected(self):
        self.assertRejected(model.optimize_capacity, {"A": [0.2, 1]}, None, 1, 4, None)
        self.assertRejected(model.optimize_capacity, {"A": [1]}, None, 1, 4, 2.5)
        self.assertRejected(model.optimize_capacity, {"A": [1]}, None, 1, 4, 3, {"A": 0.5})
        self.assertRejected(model.expected_cost, [0.2], 0, 1, 4)
        self.assertRejected(model.expected_cost, [1], 0.5, 1, 4)
        self.assertRejected(model.proportional_allocation, {"A": 1.0}, 2.5)
        self.assertRejected(model.fill_gaps, {"A": 1.5}, None, 4)
        self.assertRejected(model.simulate, ["A"], [[1.5]], [1.0], model.fixed_targets({"A": 1}), None, 1, 1)

    def test_nan_and_infinite_inputs_are_rejected(self):
        for bad in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=bad):
                self.assertRejected(model.optimize_capacity, {"A": [1, bad]}, None, 1, 4, None)
                self.assertRejected(model.optimize_capacity, {"A": [1]}, {"A": bad}, 1, 4, None)
                self.assertRejected(model.optimize_capacity, {"A": [1]}, None, bad, 4, None)
                self.assertRejected(model.optimize_capacity, {"A": [1]}, None, 1, bad, None)
                self.assertRejected(model.optimize_capacity, {"A": [1]}, None, 1, 4, bad)
                self.assertRejected(model.proportional_allocation, {"A": bad, "B": 1.0}, 3)
                self.assertRejected(model.expected_cost, [1, bad], 0, 1, 4)
                self.assertRejected(model.simulate, ["A"], [[bad]], [1.0], model.fixed_targets({"A": 1}), None, 1, 1)
                self.assertRejected(model.simulate, ["A"], [[1]], [bad], model.fixed_targets({"A": 1}), None, 1, 1)
        self.assertRejected(model.critical_ratio, "nan", 1)

    def test_negative_inputs_are_rejected(self):
        self.assertRejected(model.optimize_capacity, {"A": [-1, 2]}, None, 1, 4, None)
        self.assertRejected(model.optimize_capacity, {"A": [1]}, {"A": -2.0}, 1, 4, None)
        self.assertRejected(model.optimize_capacity, {"A": [1]}, {"A": 0.0}, 1, 4, None)
        self.assertRejected(model.optimize_capacity, {"A": [1]}, None, -0.05, 0.3, None)
        self.assertRejected(model.optimize_capacity, {"A": [1]}, None, 1, 4, -1)
        self.assertRejected(model.proportional_allocation, {"A": -1.0, "B": 3.0}, 2)
        self.assertRejected(model.proportional_allocation, {"A": 1.0}, -2)

    def test_keys_must_be_unique_strings_that_match(self):
        self.assertRejected(model.optimize_capacity, {1: [1], "1": [2]}, None, 1, 4, None)
        self.assertRejected(model.optimize_capacity, {"A": [1], "B": [2]}, {"A": 1.0}, 1, 4, None)
        self.assertRejected(model.optimize_capacity, {"A": [1]}, None, 1, 4, 3, {"A": 0, "B": 1})
        self.assertRejected(model.fill_gaps, {"A": 1}, {"B": 1}, 4)
        self.assertRejected(model.simulate, ["A", "A"], [[1, 1]], [1.0, 1.0], lambda w, c: [0, 0], None, 1, 1)
        self.assertRejected(model.simulate, ["A"], [[1, 1]], [1.0], lambda w, c: [0], None, 1, 1)

    def test_booleans_strings_and_complex_values_are_rejected(self):
        for history in ([True, 2], np.array(["2"], dtype=object), np.array([2 + 5j]), ["2"], [None]):
            with self.subTest(history=history):
                self.assertRejected(model.optimize_capacity, {"A": history}, None, 1, 4, None)
        self.assertRejected(model.proportional_allocation, {"A": True}, 1)
        self.assertRejected(model.optimize_capacity, {"A": [1]}, {"A": True}, 1, 4, None)
        self.assertRejected(model.optimize_capacity, {"A": [1]}, None, True, 4, None)
        self.assertRejected(model.optimize_capacity, {"A": [1]}, None, 1, 4, True)

    def test_exact_values_are_checked_before_conversion(self):
        near_one = Fraction(2**54 + 1, 2**54)
        self.assertRejected(model.scale_to_capacity, {"A": near_one}, None)
        self.assertRejected(model.optimize_capacity, {"A": np.array([near_one], dtype=object)}, None, 1, 4, None)
        self.assertRejected(model.optimize_capacity, {"A": [Decimal("2.0000000000000000001")]}, None, 1, 4, None)
        self.assertEqual(model.scale_to_capacity({"A": Fraction(2**53 + 1)}, None), {"A": 2**53 + 1})
        self.assertEqual(model.fixed_targets({"A": Decimal("10")})(0, {"A": 0}), {"A": 10})
        mixed = [Decimal("2"), np.int64(3), 4.0, Fraction(4)]
        self.assertEqual(model.optimize_capacity({"A": mixed}, None, 1, 4, None), {"A": 4})

    def test_numpy_integer_rates_stay_exact(self):
        shortage = Fraction("0.30000000000000000001")
        self.assertEqual(model.critical_ratio(np.int64(1), "0.30000000000000000001"), shortage / (1 + shortage))
        self.assertEqual(model.critical_ratio(np.int64(2**62), np.int64(2**62)), Fraction(1, 2))

    def test_empty_histories_are_rejected(self):
        self.assertRejected(model.optimize_capacity, {"A": []}, None, 1, 4, None)
        self.assertRejected(model.expected_cost, [], 0, 1, 4)


if __name__ == "__main__":
    unittest.main()
