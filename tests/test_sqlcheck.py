"""Tests for the SQL check of the published reconciliation, reversal pairs and weekly sales.

The fixture (tests/fixtures/sql) is a few dozen invoice lines over two sheets with planted
cases: a reversal across the sheets and across a week boundary, two candidate sales for
one credit, repeated identical sales and credits, a credit exactly 24 hours later, one 25
hours later, anonymous and same-minute credits, a charge code reversed, an overlap copy,
and one row of every other role. Its three published files were checked by hand against
the rules; each test below plants one kind of error in them.
"""

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synthetic  # noqa: E402
from synthetic import ROOT  # noqa: E402

import data  # noqa: E402
import report  # noqa: E402
import sqlcheck  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "sql"
FILES = tuple(sqlcheck.NUMBERS)
CHECKS = ["reconciliation", "pair_validity", "pair_one_use", "pair_maximality", "pair_most_recent", "weekly_sales"]
UK = "United Kingdom"
OLDER, NEWER = data.SHEETS


def fixture_source() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "source.csv", dtype={"invoice": str, "stock_code": str, "description": str})


def read(path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = data.classify(fixture_source())

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.reset()

    def tearDown(self):
        self.temporary.cleanup()

    def reset(self):
        """Put back the fixture's published files."""
        for name in FILES:
            shutil.copy(FIXTURES / name, self.folder / name)

    def failing(self) -> set:
        results = sqlcheck.run_checks(self.ledger, self.folder, UK)
        self.assertEqual(list(results), CHECKS)
        return {name for name, rows in results.items() if len(rows)}

    def edit(self, name, change):
        frame = change(read(self.folder / name))
        frame.to_csv(self.folder / name, index=False)

    def pair(self, sale_row, credit_row, sale_sheet=NEWER, credit_sheet=NEWER) -> dict:
        """A pair row describing two ledger rows correctly, whether or not they may pair."""
        rows = self.ledger.set_index(["sheet", "source_row"])
        sale, credit = rows.loc[(sale_sheet, sale_row)], rows.loc[(credit_sheet, credit_row)]
        customer = "" if pd.isna(sale["customer_id"]) else str(sale["customer_id"])
        return {
            "sku": sale["sku"], "customer_id": customer, "price": repr(float(sale["price"])),
            "units": str(sale["quantity"]), "code_class": sale["code_class"],
            "sale_sheet": sale_sheet, "sale_row": str(sale_row),
            "sale_invoice": sale["invoice"], "sale_time": str(sale["timestamp"]), "sale_country": sale["country"],
            "credit_sheet": credit_sheet, "credit_row": str(credit_row), "credit_invoice": credit["invoice"],
            "credit_time": str(credit["timestamp"]), "credit_country": credit["country"],
            "lag_minutes": repr((credit["timestamp"] - sale["timestamp"]).total_seconds() / 60), "prompt": "True",
        }

    def add_pair(self, *rows, **sheets):
        self.edit("reversal_pairs.csv", lambda frame: pd.concat(
            [frame, pd.DataFrame([self.pair(*rows, **sheets)])], ignore_index=True))

    def drop_pair(self, sale_row):
        self.edit("reversal_pairs.csv", lambda frame: frame.loc[frame["sale_row"].ne(str(sale_row))])

    def test_the_published_files_agree(self):
        self.assertEqual(self.failing(), set())

    def test_the_fixture_files_are_what_the_pipeline_publishes(self):
        expected = {  # (sale sheet, row) -> (credit sheet, row), worked out by hand
            (OLDER, 5): (NEWER, 4),  # across the sheets and a week boundary
            (NEWER, 2): (NEWER, 3),  # the older sheet's overlap copy of the sale never pairs
            (NEWER, 6): (NEWER, 7),  # the most recent of two candidate sales
            (NEWER, 9): (NEWER, 10), (NEWER, 8): (NEWER, 11),  # repeated sales and credits
            (NEWER, 12): (NEWER, 13),  # repeated credits: the second one stays unpaired
            (NEWER, 15): (NEWER, 16),  # sold on Sunday, credited on Monday
            (NEWER, 19): (NEWER, 20),  # exactly 24 hours
            (NEWER, 25): (NEWER, 26), (NEWER, 27): (NEWER, 28),  # France, and a charge code
        }
        pairs = read(FIXTURES / "reversal_pairs.csv")
        published = {(row.sale_sheet, int(row.sale_row)): (row.credit_sheet, int(row.credit_row))
                     for row in pairs.itertuples()}
        self.assertEqual(published, expected)
        report.write_csv(data.reversal_pairs(self.ledger), self.folder / "pairs.csv")
        report.write_csv(data.reconciliation(self.ledger), self.folder / "roles.csv")
        self.assertEqual((self.folder / "pairs.csv").read_bytes(), (FIXTURES / "reversal_pairs.csv").read_bytes())
        self.assertEqual((self.folder / "roles.csv").read_bytes(), (FIXTURES / "reconciliation.csv").read_bytes())
        weekly = read(FIXTURES / "weekly_sales.csv")
        panel = data.SalesPanel(self.ledger, data.PRIMARY_RULES, UK)
        for row in weekly.itertuples():
            week = pd.Timestamp(row.week_start)
            self.assertEqual(int(row.units), panel.matrix(None, [row.sku]).at[week, row.sku])
            self.assertEqual(int(row.units_at_week_close), panel.matrix(week + data.WEEK, [row.sku]).at[week, row.sku])
        self.assertEqual(weekly.loc[weekly["sku"].eq("85123A"), "units_at_week_close"].tolist(), ["24", "16", "5", "0"])

    def test_a_changed_reconciliation_count_is_found(self):
        def change(frame):
            frame.loc[frame["sheet"].eq(NEWER) & frame["role"].eq("merchandise_sale"), "units"] = "40"
            return frame
        self.edit("reconciliation.csv", change)
        self.assertEqual(self.failing(), {"reconciliation"})

    def test_a_missing_reconciliation_role_is_found(self):
        self.edit("reconciliation.csv", lambda frame: frame.loc[frame["role"].ne("zero_price")])
        self.assertEqual(self.failing(), {"reconciliation"})

    def test_pairs_that_break_the_rule_are_found(self):
        cases = {
            "credit 25 hours later": (17, 18),
            "anonymous customer": (21, 22),
            "credit in the same minute": (23, 24),
        }
        for label, rows in cases.items():
            with self.subTest(label):
                self.reset()
                self.add_pair(*rows)
                self.assertEqual(self.failing(), {"pair_validity", "reconciliation", "weekly_sales"})

    def test_a_pair_row_that_misdescribes_its_lines_is_found(self):
        def change(frame):
            frame.loc[frame["sale_row"].eq("2"), "lag_minutes"] = "31.0"
            return frame
        self.edit("reversal_pairs.csv", change)
        self.assertEqual(self.failing(), {"pair_validity"})

    def test_a_sale_used_twice_is_found(self):
        # Pairing each credit with its nearest earlier sale gives both repeated credits the same sale.
        self.add_pair(12, 14)
        self.assertEqual(self.failing(), {"pair_one_use", "reconciliation"})

    def test_a_repeated_pair_row_is_found(self):
        self.edit("reversal_pairs.csv", lambda frame: pd.concat([frame, frame.iloc[[3]]], ignore_index=True))
        self.assertEqual(self.failing(), {"pair_one_use"})

    def test_a_credit_left_unpaired_beside_a_free_sale_is_found(self):
        with self.subTest("France"):
            self.drop_pair(25)
            self.assertEqual(self.failing(), {"pair_maximality", "reconciliation"})
        with self.subTest("one of the repeated sales"):
            self.reset()
            self.drop_pair(8)
            self.assertEqual(self.failing(), {"pair_maximality", "reconciliation", "weekly_sales"})

    def test_a_credit_that_skips_the_most_recent_sale_is_found(self):
        # Credit C540006 taking the 10:00 sale instead of the 12:00 one changes no total.
        replacement = self.pair(5, 7)
        def change(frame):
            frame.loc[frame["sale_row"].eq("6"), list(replacement)] = list(replacement.values())
            return frame
        self.edit("reversal_pairs.csv", change)
        self.assertEqual(self.failing(), {"pair_most_recent"})

    def test_weekly_sales_that_differ_from_the_lines_are_found(self):
        def at_close(frame):  # as if Monday's credit were known when the Sunday sale's week closed
            frame.loc[frame["week_start"].eq("2011-03-07") & frame["sku"].eq("85123A"), "units_at_week_close"] = "0"
            return frame

        def revenue(frame):
            frame.loc[frame["week_start"].eq("2011-03-07") & frame["sku"].eq("22423"), "revenue"] = "51.01"
            return frame

        def closure(frame):
            frame.loc[frame["week_start"].eq("2011-03-28"), "closure"] = "False"
            return frame

        cases = {
            "units at the week's close": at_close, "revenue": revenue, "closure": closure,
            "a missing week": lambda frame: frame.loc[frame["week_start"].ne("2011-03-14")],
            "a missing product-week": lambda frame: frame.drop(index=3),
            "a repeated product-week": lambda frame: pd.concat([frame, frame.iloc[[3]]]),
        }
        for label, change in cases.items():
            with self.subTest(label):
                self.reset()
                self.edit("weekly_sales.csv", change)
                self.assertEqual(self.failing(), {"weekly_sales"})


class PipelineTests(unittest.TestCase):
    def test_the_check_agrees_with_the_files_the_pipeline_writes(self):
        frames = report.frames(synthetic.result())
        with tempfile.TemporaryDirectory() as folder:
            for name in FILES:
                report.write_csv(frames[name], Path(folder) / name)
            results = sqlcheck.run_checks(data.classify(synthetic.source()), folder, UK)
        self.assertEqual({name: len(rows) for name, rows in results.items()}, dict.fromkeys(CHECKS, 0))


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        for name in FILES:
            shutil.copy(FIXTURES / name, self.folder / name)
        self.config = self.folder / "config.toml"
        self.config.write_text(synthetic.config_text(), encoding="utf-8")
        self.reader = mock.patch("data.read_workbook", return_value=fixture_source())
        self.reader.start()

    def tearDown(self):
        self.reader.stop()
        self.temporary.cleanup()

    def run_main(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sqlcheck.main(["--config", str(self.config), "--input", "workbook.xlsx",
                                  "--output", str(self.folder)])
        return code, out.getvalue(), err.getvalue()

    def test_exit_status_follows_the_checks(self):
        code, out, _ = self.run_main()
        self.assertEqual((code, out.splitlines()[-1]), (0, "sql check: all 6 checks agree"))
        weekly = read(self.folder / "weekly_sales.csv")
        weekly.loc[0, "units"] = "1"
        weekly.to_csv(self.folder / "weekly_sales.csv", index=False)
        code, out, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("sql check weekly_sales: 1 disagreeing row(s)", out)
        self.assertEqual(out.splitlines()[-1], "sql check: 1 of 6 checks disagree")
        (self.folder / "reversal_pairs.csv").unlink()
        code, _, err = self.run_main()
        self.assertEqual((code, "reversal_pairs.csv" in err), (2, True))


@unittest.skipUnless(shutil.which("make"), "make is not installed")
class MakefileTests(unittest.TestCase):
    def test_verify_runs_the_check(self):
        recipe = subprocess.run(["make", "-n", "verify", "PYTHON=python3"], cwd=ROOT, capture_output=True,
                                text=True, check=True).stdout
        self.assertIn("python3 src/sqlcheck.py --config configs/published.toml --input "
                      "data/raw/online_retail_II.xlsx --output exports", recipe)


if __name__ == "__main__":
    unittest.main()
