"""Tests for reading, classifying and aggregating the invoice lines."""

import hashlib
import math
import random
import sys
import tempfile
import unittest
from dataclasses import replace
from fractions import Fraction
from functools import cache
from pathlib import Path
from statistics import median

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import data  # noqa: E402

WORKBOOK = ROOT / "data" / "raw" / "online_retail_II.xlsx"
FIXTURES = ROOT / "tests" / "fixtures" / "data"
UK = "United Kingdom"
NEWER = data.SHEETS[1]
REGISTRY = data.load_registry()


def line(invoice, code, quantity, when, price=1.0, customer=1, country=UK, description="ITEM"):
    return {"invoice": invoice, "stock_code": code, "description": description, "quantity": quantity,
            "timestamp": pd.to_datetime(when, errors="coerce"), "price": price, "customer_id": customer,
            "country": country}


def source(*lines, sheet=NEWER):
    frame = pd.DataFrame(list(lines))
    frame.insert(0, "sheet", sheet)
    frame.insert(1, "source_row", np.arange(len(frame)) + 2)
    return frame


def classify(*lines, window=data.WINDOW):
    return data.classify(source(*lines), window=window, registry=REGISTRY)


def units(ledger, rules=data.PRIMARY_RULES, cutoff=None, country=UK):
    weekly = data.SalesPanel(ledger, rules, country).weekly(cutoff)
    return {(str(row.week_start.date()), row.sku): int(row.units) for row in weekly.itertuples()}


def roles(ledger):
    return ledger["role"].astype(str).tolist()


class ReversalTests(unittest.TestCase):
    def test_prompt_reversal_sale_is_not_counted_as_sales(self):
        ledger = classify(
            line("541431", 23166, 74215, "2011-01-18 10:01", 1.04, 12346),
            line("C541433", 23166, -74215, "2011-01-18 10:17", 1.04, 12346),
            line("541500", 23166, 12, "2011-01-19 09:00", 1.04, 17000),
        )
        self.assertEqual(roles(ledger), ["prompt_reversal_sale", "prompt_reversal_credit", "merchandise_sale"])
        self.assertEqual(units(ledger), {("2011-01-17", "23166"): 12})
        self.assertEqual(units(ledger, cutoff="2011-01-24"), {("2011-01-17", "23166"): 12})
        pairs = data.reversal_pairs(ledger)
        self.assertEqual(pairs[["sale_invoice", "credit_invoice", "units", "lag_minutes"]].values.tolist(),
                         [["541431", "C541433", 74215, 16.0]])
        self.assertEqual(pairs.loc[0, "credit_time"], pd.Timestamp("2011-01-18 10:17"))

    def test_credit_25_hours_later_is_kept_in_the_ledger(self):
        ledger = classify(line("1", "A1", 5, "2011-03-01 09:00"), line("C2", "A1", -5, "2011-03-02 10:00"))
        self.assertEqual(roles(ledger), ["merchandise_sale", "ledger_credit"])
        self.assertEqual(ledger.loc[1, "reason"], "later_exact_match")
        self.assertEqual(units(ledger), {("2011-02-28", "A1"): 5})
        self.assertEqual(units(ledger, data.ALL_EXACT_RULES), {})
        self.assertEqual(units(ledger, data.ALL_EXACT_RULES, cutoff="2011-03-02 10:00"), {("2011-02-28", "A1"): 5})
        self.assertTrue(data.reversal_pairs(ledger).empty)
        self.assertEqual(len(data.reversal_pairs(ledger, prompt_only=False)), 1)

    def test_window_includes_exactly_24_hours(self):
        ledger = classify(line("1", "A1", 5, "2011-03-01 09:00"), line("C2", "A1", -5, "2011-03-02 09:00"))
        self.assertEqual(roles(ledger), ["prompt_reversal_sale", "prompt_reversal_credit"])
        one_hour = classify(line("1", "A1", 5, "2011-03-01 09:00"), line("C2", "A1", -5, "2011-03-01 10:01"),
                            window=pd.Timedelta(1, "h"))
        self.assertEqual(roles(one_hour), ["merchandise_sale", "ledger_credit"])

    def test_credit_after_cutoff_leaves_that_cutoffs_sales_unchanged(self):
        sale = line("1", "A1", 7, "2011-03-06 23:50")  # Sunday
        other = line("2", "A1", 3, "2011-03-02 12:00")
        credit = line("C3", "A1", -7, "2011-03-07 00:10")  # Monday, next week
        with_credit, without_credit = classify(other, sale, credit), classify(other, sale)
        for cutoff in ["2011-03-07 00:00", "2011-03-07 00:10"]:
            self.assertEqual(units(with_credit, cutoff=cutoff), units(without_credit, cutoff=cutoff))
        self.assertEqual(units(with_credit, cutoff="2011-03-07 00:00"), {("2011-02-28", "A1"): 10})
        self.assertEqual(units(with_credit, cutoff="2011-03-07 00:11"), {("2011-02-28", "A1"): 3})
        self.assertEqual(units(with_credit), {("2011-02-28", "A1"): 3})

    def test_anonymous_credit_never_matches(self):
        ledger = classify(
            line("1", "A1", 4, "2011-03-01 09:00", customer=None),
            line("C2", "A1", -4, "2011-03-01 09:05", customer=None),
            line("3", "A1", 4, "2011-03-01 09:10", customer=8),
            line("C4", "A1", -4, "2011-03-01 09:15", customer=None),
        )
        self.assertEqual(roles(ledger), ["merchandise_sale", "ledger_credit", "merchandise_sale", "ledger_credit"])
        self.assertEqual(ledger["reason"].astype(str).tolist()[1::2], ["missing_customer", "missing_customer"])
        self.assertEqual(units(ledger), {("2011-02-28", "A1"): 8})

    def test_credit_then_reinvoice_is_flagged_not_removed(self):
        ledger = classify(
            line("1", "A1", 30, "2011-03-01 09:00"),
            line("C2", "A1", -30, "2011-03-10 09:00"),
            line("3", "A1", 30, "2011-03-10 09:12"),
        )
        self.assertEqual(roles(ledger), ["merchandise_sale", "ledger_credit", "merchandise_sale"])
        self.assertEqual(ledger.loc[1, "reinvoice_row"], 2)
        self.assertEqual(units(ledger), {("2011-02-28", "A1"): 30, ("2011-03-07", "A1"): 30})
        summary = data.credit_summary(ledger)
        self.assertEqual(summary[["status", "lag_bucket", "credits", "reinvoice_candidates", "reinvoiced_units"]]
                         .values.tolist(), [["later_exact_match", "7 to 28 days", 1, 1, 30]])

    def test_each_credit_takes_the_most_recent_unused_earlier_sale(self):
        ledger = classify(
            line("1", "A1", 2, "2011-03-01 09:00"),
            line("2", "A1", 2, "2011-03-01 10:00"),
            line("C3", "A1", -2, "2011-03-01 11:00"),
            line("C4", "A1", -2, "2011-03-01 12:00"),
            line("5", "A1", 2, "2011-03-01 12:00"),
        )
        self.assertEqual(ledger["pair_row"].tolist()[:4], [3, 2, 1, 0])
        self.assertTrue(pd.isna(ledger.loc[4, "pair_row"]))

    def test_pairs_need_equal_customer_code_price_and_quantity(self):
        ledger = classify(
            line("1", "A1", 2, "2011-03-01 09:00", price=1.0, customer=1),
            line("C2", "A1", -2, "2011-03-01 09:01", price=1.5, customer=1),
            line("C3", "A1", -3, "2011-03-01 09:02", price=1.0, customer=1),
            line("C4", "A1", -2, "2011-03-01 09:03", price=1.0, customer=2),
            line("C5", "B1", -2, "2011-03-01 09:04", price=1.0, customer=1),
            line("C6", "a1 ", -2, "2011-03-01 09:00", price=1.0, customer=1),
            line("C7", "a1 ", -2, "2011-03-01 09:05", price=1.0, customer=1),
        )
        self.assertEqual(ledger["pair_row"].tolist(), [6, pd.NA, pd.NA, pd.NA, pd.NA, pd.NA, 0])

    def test_matching_agrees_with_a_brute_force_search(self):
        generator = random.Random(20261006)
        start = pd.Timestamp("2011-03-01")
        for case in range(120):
            lines = []
            for i in range(generator.randint(5, 40)):
                credit = generator.random() < 0.45
                lines.append(line(
                    f"C{i}" if credit else str(i), generator.choice(["A1", "a1", "B2"]),
                    generator.choice([1, 2]) * (-1 if credit else 1),
                    start + pd.Timedelta(generator.choice(range(0, 72, 5)), "h"),
                    generator.choice([1.0, 2.5]), generator.choice([1, 2, None])))
            for window in (pd.Timedelta(24, "h"), pd.Timedelta(5, "h")):
                ledger = classify(*lines, window=window)
                pairs = ledger.loc[~ledger["credit"] & ledger["pair_row"].notna()]
                found = {(int(s), int(c)) for s, c in pairs["pair_row"].items()}
                prompt = {(int(s), int(c)) for s, c in pairs.loc[pairs["prompt"], "pair_row"].items()}
                with self.subTest(case=case, window=window):
                    self.assertEqual(found, brute_force_pairs(lines, None))
                    self.assertEqual(prompt, brute_force_pairs(lines, window))


def brute_force_pairs(lines, window):
    """Credits in time order; each takes the latest unused eligible earlier sale."""
    used, pairs = set(), set()
    order = sorted(range(len(lines)), key=lambda i: (lines[i]["timestamp"], i))
    for c in order:
        credit = lines[c]
        if not credit["invoice"].startswith("C") or credit["customer_id"] is None:
            continue
        candidates = [
            s for s, sale in enumerate(lines)
            if s not in used and not sale["invoice"].startswith("C") and sale["customer_id"] == credit["customer_id"]
            and sale["stock_code"].strip().upper() == credit["stock_code"].strip().upper()
            and sale["price"] == credit["price"] and sale["quantity"] == -credit["quantity"]
            and sale["timestamp"] < credit["timestamp"]
            and (window is None or credit["timestamp"] - sale["timestamp"] <= window)]
        if candidates:
            chosen = max(candidates, key=lambda s: (lines[s]["timestamp"], s))
            used.add(chosen)
            pairs.add((chosen, c))
    return pairs


class RegistryTests(unittest.TestCase):
    def test_charges_vouchers_and_manual_entries_are_excluded_and_counted(self):
        codes = ["DOT", "POST", "M", "m", "B", "GIFT_0001_20", "gift_0001_20", "PADS", "DCGS0003", "DCGSSBOY",
                 "SP1002", "22423"]
        ledger = classify(*[line(str(100 + i), code, 2, "2011-03-01 09:00", customer=None)
                            for i, code in enumerate(codes)])
        self.assertEqual(roles(ledger), ["non_merchandise"] * 2 + ["quarantined"] * 2 + ["non_merchandise"] * 3
                         + ["quarantined"] + ["merchandise_sale"] * 4)
        self.assertEqual(sorted(sku for _, sku in units(ledger)), ["22423", "DCGS0003", "DCGSSBOY", "SP1002"])
        counts = data.registry_exclusions(ledger).set_index("code")
        self.assertEqual(counts["rows"].to_dict(), {"B": 1, "DOT": 1, "GIFT_0001_20": 2, "M": 2, "PADS": 1, "POST": 1})
        self.assertEqual(counts.loc["M", "code_action"], "quarantine")
        self.assertEqual(len(units(ledger, data.ORIGINAL_RULES)), len(codes))

    def test_accounting_invoices_are_excluded_with_the_registry(self):
        ledger = classify(line("A563185", "B", 1, "2011-08-12 14:50", 11062.06, None),
                          line("A563186", "B", 1, "2011-08-12 14:51", -11062.06, None))
        self.assertEqual(roles(ledger), ["accounting_invoice", "accounting_invoice"])
        self.assertEqual(units(ledger), {})
        self.assertEqual(units(ledger, data.ORIGINAL_RULES), {("2011-08-08", "B"): 1})


class CodeTests(unittest.TestCase):
    def test_lowercase_code_merges_into_uppercase(self):
        ledger = classify(line("1", "85123A", 6, "2011-03-01 09:00"), line("2", "85123a", 4, "2011-03-02 09:00"),
                          line("3", "85099F", 1, "2011-03-02 09:00"), line("4", "85099f", 2, "2011-03-02 09:00"))
        self.assertEqual(units(ledger), {("2011-02-28", "85099F"): 3, ("2011-02-28", "85123A"): 10})
        aliases = data.SalesPanel(ledger, data.PRIMARY_RULES, UK).aliases()
        self.assertEqual(aliases[["sku", "stock_code", "units"]].values.tolist(),
                         [["85099F", "85099F", 1], ["85099F", "85099f", 2], ["85123A", "85123A", 6],
                          ["85123A", "85123a", 4]])
        self.assertEqual(len(units(ledger, data.ORIGINAL_RULES)), 4)

    def test_suffixes_stay_and_number_and_text_codes_agree(self):
        ledger = classify(line("1", 85048, 1, "2011-03-01"), line("2", "85048", 2, "2011-03-01"),
                          line("3", 85048.0, 4, "2011-03-01"), line("4", "85099B", 8, "2011-03-01"),
                          line("5", "85099F", 16, "2011-03-01"), line("6", "47503J ", 32, "2011-03-01"))
        self.assertEqual(units(ledger), {("2011-02-28", "47503J"): 32, ("2011-02-28", "85048"): 7,
                                         ("2011-02-28", "85099B"): 8, ("2011-02-28", "85099F"): 16})
        self.assertEqual(ledger.loc[5, "stock_code"], "47503J ")


class CalendarTests(unittest.TestCase):
    def ledger(self):
        return classify(
            line("1", "A1", 3, "2011-03-02 10:00"),  # Wednesday: first, partial week
            line("2", "B2", 5, "2011-03-08 10:00"),  # A1 sells nothing this week
            line("3", "A1", 2, "2011-03-24 10:00"),  # the week of 14 March has no rows at all
            line("4", "A1", 1, "2011-03-25 16:00"),  # Friday: last, partial week
        )

    def test_partial_weeks_are_flagged_and_interior_zero_weeks_kept(self):
        ledger = self.ledger()
        weeks = data.calendar(ledger)
        self.assertEqual([str(day.date()) for day in weeks["week_start"]],
                         ["2011-02-28", "2011-03-07", "2011-03-14", "2011-03-21"])
        self.assertEqual(weeks["complete"].tolist(), [False, True, True, False])
        self.assertEqual(weeks["closure"].tolist(), [False, False, True, False])
        matrix = data.SalesPanel(ledger, data.PRIMARY_RULES, UK).matrix(skus=["A1", "B2", "C3"])
        self.assertEqual(matrix.to_numpy().tolist(), [[3, 0, 0], [0, 5, 0], [0, 0, 0], [3, 0, 0]])

    def test_a_ledger_without_dated_rows_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no dated source rows"):
            data.calendar(classify(line("1", "A1", 1, "not a date")))

    def test_week_ending_on_the_last_source_day_is_complete(self):
        ledger = classify(line("1", "A1", 1, "2011-03-07 00:00"), line("2", "A1", 1, "2011-03-13 23:00"))
        self.assertEqual(data.calendar(ledger)["complete"].tolist(), [True])


class PriceTests(unittest.TestCase):
    def test_prices_use_only_lines_before_the_cutoff(self):
        ledger = classify(
            line("1", "A1", 1, "2011-03-01", 2.0), line("2", "A1", 1, "2011-03-02", 3.0),
            line("3", "A1", 1, "2011-03-03", 4.0, customer=5), line("C4", "A1", -1, "2011-03-03 12:00", 4.0, 5),
            line("5", "A1", 1, "2011-03-10", 40.0), line("6", "B2", 1, "2011-03-10", 9.0),
        )
        panel = data.SalesPanel(ledger, data.PRIMARY_RULES, UK)
        before = panel.prices(end="2011-03-07", cutoff="2011-03-03 12:00")
        self.assertEqual(before["A1"], 3.0)
        self.assertTrue(np.isnan(before["B2"]))
        self.assertEqual(panel.prices(end="2011-03-07", cutoff="2011-03-07")["A1"], 2.5)
        self.assertEqual(panel.prices(start="2011-03-07")["A1"], 40.0)
        self.assertEqual(panel.prices(skus=["A1", "Z9"]).fillna(-1).to_dict(), {"A1": median([2.0, 3.0, 40.0]),
                                                                               "Z9": -1})

    def test_median_is_over_lines_not_units(self):
        ledger = classify(line("1", "A1", 100, "2011-03-01", 1.0), line("2", "A1", 1, "2011-03-01", 5.0),
                          line("3", "A1", 1, "2011-03-01", 6.0))
        self.assertEqual(data.SalesPanel(ledger, data.PRIMARY_RULES, UK).prices()["A1"], 5.0)


class BulkCapTests(unittest.TestCase):
    def ledger(self):
        lines = [line(str(i), "A1", q, f"2011-03-{1 + i % 20:02d} 10:00") for i, q in enumerate(range(1, 41))]
        lines += [line("100", "A1", 500, "2011-03-21 10:00"), line("100", "A1", 250, "2011-03-21 10:00"),
                  line("101", "B2", 3, "2011-03-21 11:00"), line("200", "A1", 900, "2011-04-04 10:00")]
        return classify(*lines)

    def test_caps_are_the_rounded_up_99th_percentile_of_invoice_sku_totals(self):
        panel = data.SalesPanel(self.ledger(), data.PRIMARY_RULES, UK)
        caps = panel.bulk_caps("2011-02-28", "2011-03-28", cutoff="2011-03-28")
        self.assertEqual(caps.to_dict(), {"A1": exact_ceiling_quantile(list(range(1, 41)) + [750]), "B2": 3})
        self.assertEqual(caps["A1"], 466)  # 40 + 0.6 * 710 exactly; floating point gives 466.000000000001
        self.assertEqual(panel.bulk_caps("2011-02-28", "2011-03-21").to_dict(), {"A1": 40})

    def test_caps_apply_to_invoice_sku_totals_before_weekly_sums(self):
        panel = data.SalesPanel(self.ledger(), data.PRIMARY_RULES, UK)
        capped = panel.matrix(caps={"A1": 100}, skus=["A1", "B2"])
        plain = panel.matrix(skus=["A1", "B2"])
        self.assertEqual(plain.loc["2011-03-21"].tolist(), [750, 3])
        self.assertEqual((plain - capped).loc["2011-03-21"].tolist(), [650, 0])
        self.assertEqual((plain - capped).loc["2011-04-04"].tolist(), [800, 0])
        self.assertEqual(capped.drop(index=[pd.Timestamp("2011-03-21"), pd.Timestamp("2011-04-04")]).to_numpy()
                         .tolist(), plain.drop(index=[pd.Timestamp("2011-03-21"), pd.Timestamp("2011-04-04")])
                         .to_numpy().tolist())


    def test_caps_use_only_the_lines_inside_the_window(self):
        panel = data.SalesPanel(classify(line("1", "A1", 5, "2011-03-01"), line("1", "A1", 7, "2011-03-02")),
                                data.PRIMARY_RULES, UK)
        self.assertEqual(panel.bulk_caps(end="2011-03-02", cutoff="2011-03-02").to_dict(), {"A1": 5})
        self.assertEqual(panel.bulk_caps().to_dict(), {"A1": 12})

    def test_caps_must_be_whole_units(self):
        panel = data.SalesPanel(self.ledger(), data.PRIMARY_RULES, UK)
        for caps in ({"A1": 2.5}, {"A1": -1}):
            with self.assertRaises(ValueError):
                panel.matrix(caps=caps)
        self.assertEqual(panel.matrix(caps={"A1": np.nan}).to_numpy().tolist(), panel.matrix().to_numpy().tolist())

    def test_caps_count_a_reversed_order_only_until_its_credit_is_known(self):
        lines = [line(str(i), "A1", 1, f"2011-03-0{1 + i % 5} 10:00") for i in range(9)]
        lines += [line("50", "A1", 1000, "2011-03-07 10:00", customer=9),
                  line("C51", "A1", -1000, "2011-03-07 10:20", customer=9)]
        panel = data.SalesPanel(classify(*lines), data.PRIMARY_RULES, UK)
        self.assertEqual(panel.bulk_caps(end="2011-03-14", cutoff="2011-03-07 10:20")["A1"],
                         exact_ceiling_quantile([1] * 9 + [1000]))
        self.assertEqual(panel.bulk_caps(end="2011-03-14", cutoff="2011-03-07 10:21")["A1"], 1)


def exact_ceiling_quantile(values, share=Fraction(99, 100)):
    ordered = sorted(values)
    position = share * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return math.ceil(ordered[low] + (position - low) * (ordered[high] - ordered[low]))


class ConcentrationTests(unittest.TestCase):
    def test_anonymous_top_customer_and_top_invoice_shares(self):
        ledger = classify(
            line("1", "A1", 50, "2011-03-01", customer=7), line("2", "A1", 20, "2011-03-02", customer=7),
            line("3", "A1", 10, "2011-03-02", customer=8), line("4", "A1", 20, "2011-03-03", customer=None),
            line("5", "A1", 999, "2011-04-03", customer=9),
        )
        table = data.SalesPanel(ledger, data.PRIMARY_RULES, UK).concentration(end="2011-03-07")
        row = table.loc["A1"]
        self.assertEqual((row["units"], row["customers"], row["invoices"], row["top_customer"], row["top_invoice"]),
                         (100, 2, 4, 7, "1"))
        self.assertAlmostEqual(row["anonymous_share"], 0.20)
        self.assertAlmostEqual(row["top_customer_share"], 0.70)
        self.assertAlmostEqual(row["top_invoice_share"], 0.50)


class DescriptionTests(unittest.TestCase):
    def test_modal_description_ignores_blanks(self):
        ledger = classify(line("1", "A1", 1, "2011-03-01", description="CREAM HEART"),
                          line("2", "A1", 1, "2011-03-02", description="WHITE HEART "),
                          line("3", "A1", 1, "2011-03-03", description="WHITE HEART"),
                          line("4", "A1", 1, "2011-03-04", description=None),
                          line("5", "B2", 1, "2011-03-04", description=" "))
        panel = data.SalesPanel(ledger, data.PRIMARY_RULES, UK)
        self.assertEqual(panel.descriptions().to_dict(), {"A1": "WHITE HEART", "B2": "Unknown item"})
        self.assertEqual(panel.descriptions(end="2011-03-02")["A1"], "CREAM HEART")
        drift = panel.description_drift()
        self.assertEqual(drift[["description", "rows"]].values.tolist(), [["CREAM HEART", 1], ["WHITE HEART", 2]])


class RulesTests(unittest.TestCase):
    def test_each_published_design_step_changes_one_treatment(self):
        ledger = classify(
            line("1", "85123A", 10, "2011-03-01 09:00", customer=4), line("2", "85123a", 3, "2011-03-01 09:00"),
            line("3", "85123A", 50, "2011-03-02 09:00", customer=5),
            line("C4", "85123A", -50, "2011-03-02 09:16", customer=5),
            line("5", "DOT", 1, "2011-03-02 09:00", 185.47), line("A6", "B", 1, "2011-03-02 09:00", 9.0, None))
        steps = [data.ORIGINAL_RULES]
        for change in ({"reversals": "prompt"}, {"registry": True}, {"normalize_case": True}):
            steps.append(replace(steps[-1], **change))
        self.assertEqual(steps[-1], data.PRIMARY_RULES)
        week = "2011-02-28"
        self.assertEqual([units(ledger, rules) for rules in steps], [
            {(week, "85123A"): 60, (week, "85123a"): 3, (week, "DOT"): 1, (week, "B"): 1},
            {(week, "85123A"): 10, (week, "85123a"): 3, (week, "DOT"): 1, (week, "B"): 1},
            {(week, "85123A"): 10, (week, "85123a"): 3},
            {(week, "85123A"): 13},
        ])


class ValidationTests(unittest.TestCase):
    def test_fractional_and_nonfinite_quantities_are_invalid_and_counted(self):
        ledger = classify(line("1", "A1", 0.2, "2011-03-01"), line("2", "A1", float("inf"), "2011-03-01"),
                          line("3", "A1", 2, "2011-03-01", float("inf")), line("4", "A1", None, "2011-03-01"),
                          line("5", "A1", 2, "not a date"), line("6", "A1", 0, "2011-03-01"),
                          line("7", "A1", 3, "2011-03-01"))
        self.assertEqual(roles(ledger), ["invalid"] * 6 + ["merchandise_sale"])
        counts = data.reconciliation(ledger, by_reason=True).set_index("reason")["rows"].to_dict()
        self.assertEqual(counts, {"fractional_quantity": 1, "nonfinite_quantity": 1, "nonfinite_price": 1,
                                  "missing_quantity": 1, "missing_timestamp": 1, "zero_quantity": 1, "": 1})
        self.assertEqual(units(ledger), {("2011-02-28", "A1"): 3})

    def test_negative_lines_without_a_credit_invoice_are_stock_adjustments(self):
        ledger = classify(line("1", "A1", -40, "2011-03-01", 0.0, None, description="Damaged"),
                          line("C2", "A1", -1, "2011-03-01", 1.0, None), line("3", "A1", 5, "2011-03-01", 0.0))
        self.assertEqual(roles(ledger), ["stock_adjustment", "ledger_credit", "zero_price"])

    def test_rules_reject_unknown_settings(self):
        with self.assertRaises(ValueError):
            data.DataRules(reversals="partial")
        with self.assertRaises(ValueError):
            data.DataRules(registry="yes")
        self.assertEqual(data.ORIGINAL_RULES, data.DataRules("none", False, False))

    def test_text_customer_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            classify(line("1", "A1", 1, "2011-03-01", customer="abc"))


class ReconciliationTests(unittest.TestCase):
    def ledger(self):
        return classify(
            line("1", "A1", 5, "2011-03-01 09:00"), line("C2", "A1", -5, "2011-03-01 09:30"),
            line("3", "A1", 2, "2011-03-01 10:00"), line("C4", "A1", -2, "2011-03-05 10:00"),
            line("C5", "A1", -9, "2011-03-05 11:00"), line("6", "DOT", 1, "2011-03-05", 185.47),
            line("7", "A1", -3, "2011-03-06", 0.0, None), line("8", "A1", 4, "2011-03-07", 0.0),
            line("9", "B2", 1.5, "2011-03-07"), line("A10", "B", 1, "2011-03-07", 9.0, None),
            line("11", "M", 6, "2011-03-08", 2.0, country="France"), line("12", "B2", 8, "2011-03-08", 0.5),
        )

    def test_roles_sum_to_the_source(self):
        ledger = self.ledger()
        table = data.reconciliation(ledger)
        self.assertEqual(table["rows"].sum(), 12)
        self.assertEqual(table["units"].sum(), 5 - 5 + 2 - 2 - 9 + 1 - 3 + 4 + 1 + 6 + 8)
        self.assertAlmostEqual(table["value"].sum(), 185.47 + 9.0 + 12.0 + 4.0 - 9.0)
        self.assertEqual(set(table["role"].astype(str)), {
            "prompt_reversal_sale", "prompt_reversal_credit", "merchandise_sale", "ledger_credit", "non_merchandise",
            "stock_adjustment", "zero_price", "invalid", "accounting_invoice", "quarantined"})
        self.assertEqual(data.reconciliation(ledger, UK)["rows"].sum(), 11)

    def test_bridge_from_accepted_lines_to_complete_weeks(self):
        bridge = data.bridge(self.ledger(), UK)
        self.assertEqual(bridge[["stage", "rows", "units"]].values.tolist(), [
            ["accepted", 5, 17], ["merchandise", 3, 15], ["after_prompt_reversals", 2, 10],
            ["complete_weeks", 0, 0]])

    def test_credit_summary_by_status_and_lag(self):
        summary = data.credit_summary(self.ledger()).set_index(["status", "lag_bucket"])
        self.assertEqual(summary["credits"].to_dict(), {
            ("prompt_reversal", "up to 1 hour"): 1, ("later_exact_match", "1 to 7 days"): 1,
            ("no_earlier_equal_sale", "unmatched"): 1})
        self.assertEqual(summary["units"].sum(), 16)


class WorkbookReadingTests(unittest.TestCase):
    HEADER = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]

    def write(self, directory, older, newer):
        path = Path(directory) / "tiny.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for name, rows in zip(data.SHEETS, (older, newer)):
                pd.DataFrame(rows, columns=self.HEADER).to_excel(writer, sheet_name=name, index=False)
        return path

    def rows(self):
        early = [[489434, 85048, "LIGHT", 12, pd.Timestamp("2009-12-01 07:45"), 6.95, 13085.0, UK],
                 ["C489449", "22087", "PAPER", -12, pd.Timestamp("2009-12-01 10:33"), 2.95, 16321.0, "Australia"]]
        shared = [[536365, "85123A", "HEART", 6, pd.Timestamp("2010-12-01 08:26"), 2.55, 17850.0, UK],
                  [536366, 22633, "HAND WARMER", 6, pd.Timestamp("2010-12-01 08:28"), 1.85, None, UK]]
        late = [[581587, 22138, "BAKING SET", 3, pd.Timestamp("2011-12-09 12:50"), 4.95, 12680.0, "France"]]
        return early, shared, late

    def test_identical_overlap_is_dropped_once(self):
        early, shared, late = self.rows()
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, early + shared[::-1], shared + late)
            combined = data.read_workbook(path, overlap_rows=2, union_rows=5)
        self.assertEqual(combined["overlap"].tolist(), [False, False, True, True, False, False, False])
        self.assertEqual(combined["source_row"].tolist(), [2, 3, 4, 5, 2, 3, 4])
        ledger = data.classify(combined, registry=REGISTRY)
        self.assertEqual(roles(ledger)[2:4], ["overlap", "overlap"])
        self.assertEqual(units(ledger), {("2009-11-30", "85048"): 12, ("2010-11-29", "85123A"): 6,
                                         ("2010-11-29", "22633"): 6})
        self.assertEqual(data.reconciliation(ledger)["rows"].sum(), 7)
        self.assertEqual(ledger["customer_id"].tolist()[:2], [13085, 16321])

    def test_overlap_compares_values_not_inferred_types(self):
        early, shared, late = self.rows()
        blank = [[581588, 22139, "TEA SET", None, pd.Timestamp("2011-12-09 12:55"), 4.95, 12680.0, "France"]]
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, early + shared, shared + late + blank)
            sheets = pd.read_excel(path, sheet_name=list(data.SHEETS))
            combined = data.read_workbook(path, overlap_rows=2, union_rows=6)
        self.assertEqual([str(sheets[name]["Quantity"].dtype) for name in data.SHEETS], ["int64", "float64"])
        self.assertEqual(roles(data.classify(combined, registry=REGISTRY))[-1], "invalid")

    def test_differing_overlap_is_rejected(self):
        early, shared, late = self.rows()
        changed = [shared[0][:3] + [7] + shared[0][4:], shared[1]]
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, early + changed, shared + late)
            with self.assertRaisesRegex(ValueError, "overlapping rows differ"):
                data.read_workbook(path, overlap_rows=None, union_rows=None)
            with self.assertRaisesRegex(ValueError, "expected 9"):
                data.read_workbook(self.write(directory, early + shared, shared + late), overlap_rows=9)


@cache
def workbook():
    combined = data.read_workbook(WORKBOOK)
    return combined, data.classify(combined), data.classify(combined.loc[combined["sheet"].eq(NEWER)])


@unittest.skipUnless(WORKBOOK.exists(), "the Online Retail II workbook is not downloaded")
class RealWorkbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.ledger, cls.newer = workbook()

    def test_sheets_combine_without_the_overlap(self):
        self.assertEqual(len(self.source), 1_067_371)
        self.assertEqual(int(self.source["overlap"].sum()), 22_523)
        self.assertEqual(int((~self.source["overlap"]).sum()), 1_044_848)
        weeks = data.calendar(self.ledger)
        self.assertEqual(int(weeks["complete"].sum()), 104)
        self.assertEqual(str(weeks.loc[weeks["complete"], "week_start"].min().date()), "2009-12-07")
        self.assertEqual([str(day.date()) for day in weeks.loc[weeks["closure"], "week_start"]],
                         ["2009-12-28", "2010-12-27"])

    def test_prompt_reversals_match_the_known_pairs(self):
        pairs = data.reversal_pairs(self.newer)
        uk = pairs.loc[pairs["sale_country"].eq(UK)]
        self.assertEqual((len(uk), int(uk["units"].sum())), (524, 176_604))
        both = data.reversal_pairs(self.ledger)
        both_uk = both.loc[both["sale_country"].eq(UK)]
        self.assertEqual((len(both_uk), int(both_uk["units"].sum())), (1_075, 210_153))
        known = both.set_index("sale_invoice").loc[["541431", "581483"]]
        self.assertEqual(known[["credit_invoice", "units", "lag_minutes"]].values.tolist(),
                         [["C541433", 74_215, 16.0], ["C581484", 80_995, 12.0]])
        newer_sales = both.loc[both["sale_sheet"].eq(NEWER), ["sale_row", "credit_row"]]
        self.assertTrue(newer_sales.reset_index(drop=True).equals(pairs[["sale_row", "credit_row"]]))

    def test_reconciliation_and_bridge(self):
        table = data.reconciliation(self.ledger)
        self.assertEqual(int(table["rows"].sum()), 1_067_371)
        self.assertEqual(int(table["units"].sum()), int(self.source["quantity"].sum()))
        bridge = data.bridge(self.newer, UK)
        self.assertEqual(bridge[["rows", "units"]].values.tolist()[:3],
                         [[485_123, 4_662_390], [484_004, 4_654_355], [483_490, 4_477_812]])
        flagged = self.newer.loc[self.newer["reinvoice_row"].notna()]
        self.assertEqual((len(flagged), int(-flagged["quantity"].sum())), (96, 10_151))
        excluded = data.registry_exclusions(self.newer, UK).set_index("code")
        self.assertEqual((int(excluded["rows"].sum()), int(excluded["units"].sum())), (1_119, 8_035))
        self.assertEqual(excluded.loc["DOT", "rows"], 706)
        self.assertEqual(data.repeated_lines(self.ledger)["repeated_rows"].tolist(), [6_865, 5_268])

    def test_original_treatment_reproduces_the_published_inputs(self):
        """Fixtures: weekly_demand_matrix(clean_transactions(...)) at commit 0e33242, 2010-2011 sheet.

        original_weekly_units.csv holds the 20 published SKUs, weekly totals and active-SKU
        counts; original_digests.csv holds SHA-256 digests of every non-zero SKU-week
        ("week,sku,units" lines sorted) and every SKU price ("sku,repr(price)" sorted).
        """
        expected = pd.read_csv(FIXTURES / "original_weekly_units.csv", index_col="week_start", parse_dates=True)
        prices = pd.read_csv(FIXTURES / "original_prices.csv", dtype={"sku": str}, float_precision="round_trip")
        prices = prices.set_index("sku")["price"]
        panel = data.SalesPanel(self.newer, data.ORIGINAL_RULES, UK)
        matrix = panel.matrix()
        self.assertTrue(matrix.index.equals(pd.DatetimeIndex(expected.index)))
        self.assertEqual(matrix.shape[1], 3_916)
        skus = [column for column in expected.columns if column not in ("all_skus", "active_skus")]
        self.assertEqual(matrix[skus].to_numpy().tolist(), expected[skus].to_numpy().tolist())
        self.assertEqual(matrix.sum(axis=1).tolist(), expected["all_skus"].tolist())
        self.assertEqual(matrix.gt(0).sum(axis=1).tolist(), expected["active_skus"].tolist())
        self.assertEqual(panel.prices(skus=skus).tolist(), prices.loc[skus].tolist())
        digests = pd.read_csv(FIXTURES / "original_digests.csv").set_index("table")
        cells = matrix.stack()
        cells = cells[cells.ne(0)]
        weekly = "\n".join(f"{week:%Y-%m-%d},{sku},{units}" for (week, sku), units in sorted(cells.items()))
        all_prices = panel.prices()
        price_text = "\n".join(f"{sku},{float(all_prices[sku])!r}" for sku in sorted(all_prices.index))
        self.assertEqual((len(cells), hashlib.sha256(weekly.encode()).hexdigest()),
                         tuple(digests.loc["weekly_units", ["rows", "sha256"]]))
        self.assertEqual((len(all_prices), hashlib.sha256(price_text.encode()).hexdigest()),
                         tuple(digests.loc["prices", ["rows", "sha256"]]))


if __name__ == "__main__":
    unittest.main()
