import itertools
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from replenishment import (  # noqa: E402
    backtest_forecasts,
    clean_transactions,
    expected_cost,
    optimize_capacity,
    proportional_allocation,
)


class CleaningTests(unittest.TestCase):
    def test_cleaning_separates_positive_sales_from_returns_and_invalid_rows(self):
        frame = pd.DataFrame(
            [
                ["100", "A", "Item A", 3, "2026-01-01", 2.5, 1, "United Kingdom"],
                ["C101", "A", "Item A", -1, "2026-01-02", 2.5, 1, "United Kingdom"],
                ["102", "B", "Item B", 2, "bad-date", 4.0, 2, "United Kingdom"],
                ["103", "C", "", 1, "2026-01-03", 5.0, 3, "France"],
            ],
            columns=[
                "Invoice",
                "StockCode",
                "Description",
                "Quantity",
                "InvoiceDate",
                "Price",
                "Customer ID",
                "Country",
            ],
        )
        cleaned, summary = clean_transactions(frame)
        self.assertEqual(list(cleaned["sku"]), ["A", "C"])
        self.assertEqual(summary.source_rows, 4)
        self.assertEqual(summary.cancellations_or_returns, 1)
        self.assertEqual(summary.invalid_rows, 1)
        self.assertEqual(summary.missing_descriptions, 1)


class OptimizationTests(unittest.TestCase):
    def test_expected_cost_balances_overage_and_underage(self):
        samples = [0, 2, 4]
        self.assertAlmostEqual(expected_cost(samples, 2, holding=1.0, shortage=3.0), 8 / 3)

    def test_optimizer_matches_brute_force(self):
        train = pd.DataFrame({"A": [0, 1, 2, 3], "B": [0, 0, 2, 5]})
        holding = pd.Series({"A": 1.0, "B": 1.5})
        shortage = pd.Series({"A": 4.0, "B": 5.0})
        capacity = 4
        optimized = optimize_capacity(train, holding, shortage, capacity)
        optimized_cost = sum(
            expected_cost(train[sku], optimized[sku], holding[sku], shortage[sku])
            for sku in train.columns
        )
        brute_force = min(
            sum(
                expected_cost(train[sku], quantities[index], holding[sku], shortage[sku])
                for index, sku in enumerate(train.columns)
            )
            for quantities in itertools.product(range(capacity + 1), repeat=2)
            if sum(quantities) <= capacity
        )
        self.assertAlmostEqual(optimized_cost, brute_force)
        self.assertLessEqual(sum(optimized.values()), capacity)

    def test_proportional_allocation_uses_exact_capacity(self):
        allocation = proportional_allocation({"A": 4.0, "B": 3.0, "C": 1.0}, 7)
        self.assertEqual(sum(allocation.values()), 7)
        self.assertEqual(allocation, {"A": 3, "B": 3, "C": 1})


class ForecastTests(unittest.TestCase):
    def test_backtest_returns_all_methods_and_finite_metrics(self):
        train = pd.DataFrame({"A": [1, 2, 3, 4], "B": [2, 2, 2, 2]})
        test = pd.DataFrame({"A": [5, 6], "B": [2, 2]})
        result = backtest_forecasts(train, test)
        self.assertEqual(
            set(result["method"]),
            {"Historical mean", "Trailing 4 weeks", "Exponential smoothing"},
        )
        self.assertTrue(np.isfinite(result[["wape", "bias", "mae"]].to_numpy()).all())


if __name__ == "__main__":
    unittest.main()

