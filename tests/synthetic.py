"""A small two-sheet source and configuration for the study, report and CLI tests.

Two years of invoice lines for a handful of products, shaped like the workbook: the
older sheet runs to 9 December 2010 and repeats the newer sheet's first days, two weeks
have no invoices at all, and a few planted lines exercise the data rules (a charge code,
a lower-case code, a prompt reversal, one that crosses a week boundary and a later
credit).
"""

import sys
import tomllib
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import data  # noqa: E402
import experiment  # noqa: E402

UK = "United Kingdom"
FIRST, LAST = pd.Timestamp("2009-12-01"), pd.Timestamp("2011-12-09")
NEWER_STARTS, OLDER_ENDS = pd.Timestamp("2010-12-01"), pd.Timestamp("2010-12-09 23:59")
CLOSED = (pd.Timestamp("2009-12-28"), pd.Timestamp("2010-12-27"))
PRODUCTS = {"10001": (4.0, 30), "10002": (2.5, 60), "10003": (9.0, 12), "85123A": (2.95, 40), "20000": (1.0, 3)}
PRICE_CHANGE = pd.Timestamp("2011-06-01")  # 10003 costs 10.0 from then on

CONFIG = """
[input]
sha256 = "%s"
bytes = %d
country = "United Kingdom"
reversal_window_hours = 24

[cohort]
skus = 4
min_active_weeks = 20
selection_weeks = 52
evaluation_weeks = %d

[comparison]
baselines = ["scaled_fractile", "proportional"]

[primary]
id = "primary"
label = "Primary configuration"
holding_rate = 0.05
shortage_rate = 0.30
capacity_factor = 1.0
window = "trailing_52"

[bootstrap]
block_weeks = 4
check_block_weeks = [2]
resamples = 300
seed = 11
confidence = 0.9

[[sensitivity]]
id = "ratio_0.95"
label = "Critical ratio 0.95"
critical_ratio = 0.95

[[sensitivity]]
id = "seasonal_analog"
label = "Same weeks a year earlier"
window = "seasonal_analog"

[[sensitivity]]
id = "bulk_cap"
label = "History capped"
bulk_cap_quantile = 0.9

[bridge]
sheet = "Year 2010-2011"
skus = 3
min_active_weeks = 10
holdout_weeks = 12
capacity_share = 0.85
steps = ["original", "prompt_reversals", "code_registry", "case_normalization", "complete_weeks",
         "training_prices", "inverse_ecdf_capacity"]
"""


def config_text(sha256="0" * 64, size=1, evaluation_weeks=52) -> str:
    return CONFIG % (sha256, size, evaluation_weeks)


def config(**changes) -> experiment.Config:
    return experiment.parse_config(tomllib.loads(config_text(**changes)))


def line(invoice, code, quantity, when, price, customer=12346, description=None):
    return {"invoice": str(invoice), "stock_code": code, "description": description or f"ITEM {code}",
            "quantity": quantity, "timestamp": pd.Timestamp(when), "price": price, "customer_id": customer,
            "country": UK}


def lines(seed=7) -> list[dict]:
    """Every invoice line of the two years, in time order."""
    rng = np.random.default_rng(seed)
    rows, number = [], 500000
    for when in pd.date_range(FIRST + pd.Timedelta(10, "h"), LAST + pd.Timedelta(10, "h"), freq="D"):
        monday = when.normalize() - pd.Timedelta(when.weekday(), "D")
        if monday in CLOSED or when.weekday() not in (1, 3, 4):
            continue
        autumn = 1.6 if when.month in (9, 10, 11) else 1.0
        for code, (price, level) in PRODUCTS.items():
            if rng.random() < (0.25 if code == "20000" else 0.8):
                number += 1
                if code == "10003" and when >= PRICE_CHANGE:
                    price = 10.0
                written = "85123a" if code == "85123A" and rng.random() < 0.1 else code
                customer = [12346, 12347, 12348, None][rng.integers(4)]
                rows.append(line(number, written, int(rng.poisson(level * autumn)) + 1,
                                 when + pd.Timedelta(int(rng.integers(0, 400)), "min"), price, customer))
        if when.weekday() == 3:
            number += 1
            rows.append(line(number, "DOT", 1, when + pd.Timedelta(5, "h"), 15.0, None, "DOTCOM POSTAGE"))
    rows += [
        line(900001, "10001", 5000, "2011-03-15 10:00", 4.0, 12346),  # reversed 16 minutes later
        line("C900002", "10001", -5000, "2011-03-15 10:16", 4.0, 12346),
        line(900003, "10003", 30, "2011-02-13 23:50", 9.0, 12348),  # reversed after the week ends
        line("C900004", "10003", -30, "2011-02-14 00:10", 9.0, 12348),
        line(900005, "10002", 400, "2011-05-10 11:00", 2.5, 12347),  # credited four days later
        line("C900006", "10002", -400, "2011-05-14 09:00", 2.5, 12347),
    ]
    return sorted(rows, key=lambda row: (row["timestamp"], row["invoice"]))


def source(rows=None) -> pd.DataFrame:
    """Both sheets as `data.read_workbook` returns them."""
    rows = pd.DataFrame(lines() if rows is None else rows)

    def sheet(frame, name):
        frame = frame.reset_index(drop=True)
        frame.insert(0, "sheet", name)
        frame.insert(1, "source_row", np.arange(len(frame)) + 2)
        return frame

    older = sheet(rows.loc[rows["timestamp"].le(OLDER_ENDS)], data.SHEETS[0])
    newer = sheet(rows.loc[rows["timestamp"].ge(NEWER_STARTS)], data.SHEETS[1])
    return data.combine_sheets(older, newer)


@cache
def result(evaluation_weeks=52) -> experiment.Result:
    return experiment.run(config(evaluation_weeks=evaluation_weeks), source())


@cache
def study() -> experiment.Study:
    return experiment.Study(config(), data.classify(source()))
