#!/usr/bin/env python3
"""Check the published reconciliation, reversal pairs and weekly sales in SQLite.

    python src/sqlcheck.py [--config FILE] [--input XLSX] [--output DIR]

Classifies the workbook's rows, loads the ledger's row fields and three published files
(reconciliation.csv, reversal_pairs.csv and weekly_sales.csv from the output folder) into
an in-memory SQLite database, and runs sql/reconciliation.sql, which works out the roles,
the pairing rule and the weekly sums again. Prints each check's result; the exit status is
1 when any check disagrees and 2 on an error.
"""

from __future__ import annotations

import argparse
import contextlib
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd

import data
import experiment

SQL = Path(__file__).resolve().parents[1] / "sql" / "reconciliation.sql"
FIELDS = ("sheet", "source_row", "overlap", "valid", "credit", "accounting", "code_class", "code_action",
          "invoice", "sku", "customer_id", "price", "quantity", "country")
NUMBERS = {  # numeric columns of each published file; the others are compared as text
    "reconciliation.csv": ("rows", "units", "value"),
    "reversal_pairs.csv": ("customer_id", "price", "units", "sale_row", "credit_row", "lag_minutes"),
    "weekly_sales.csv": ("units", "units_at_week_close", "revenue"),
}
SHOWN = 10  # disagreeing rows printed per check


def run_checks(ledger: pd.DataFrame, exports, country: str, window=data.WINDOW) -> dict[str, pd.DataFrame]:
    """Each check's disagreeing rows by check name, in file order; all empty means agreement."""
    with contextlib.closing(sqlite3.connect(":memory:")) as db:
        load(db, ledger, Path(exports), country, pd.Timedelta(window))
        setup, *parts = re.split(r"^-- check: (\w+)\n", SQL.read_text(encoding="utf-8"), flags=re.MULTILINE)
        db.executescript(setup)
        return {name: pd.read_sql_query(query, db) for name, query in zip(parts[::2], parts[1::2])}


def load(db: sqlite3.Connection, ledger: pd.DataFrame, exports: Path, country: str, window: pd.Timedelta):
    fields = pd.DataFrame(index=ledger.index)
    for name in FIELDS:
        column = ledger[name]
        if column.dtype == bool:
            fields[name] = column.astype(int)
        elif isinstance(column.dtype, pd.CategoricalDtype):
            fields[name] = column.astype(object).where(column.notna(), None)
        else:
            fields[name] = column
    stamps = ledger["timestamp"]
    fields["t"] = pd.array(stamps.to_numpy("datetime64[ns]").astype("int64"), dtype="Int64")
    fields.loc[stamps.isna().to_numpy(), "t"] = pd.NA
    fields.to_sql("ledger", db, index=False)
    for name, numbers in NUMBERS.items():
        frame = pd.read_csv(exports / name, dtype=str, keep_default_na=False)
        for column in numbers:
            frame[column] = [float(text) if text else None for text in frame[column]]  # exact; blank is NULL
        frame.to_sql(name.removesuffix(".csv"), db, index=False)
    db.execute("CREATE TABLE params (window_ns INTEGER, country TEXT)")
    db.execute("INSERT INTO params VALUES (?, ?)", (window.value, country))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check published files against the ledger in SQLite.")
    parser.add_argument("--config", type=Path, default=Path("configs/published.toml"))
    parser.add_argument("--input", type=Path, default=Path("data/raw/online_retail_II.xlsx"))
    parser.add_argument("--output", type=Path, default=Path("exports"))
    args = parser.parse_args(argv)
    try:
        config = experiment.load_config(args.config)
        window = pd.Timedelta(config.reversal_hours, "h")
        ledger = data.classify(data.read_workbook(args.input), window=window)
        results = run_checks(ledger, args.output, config.country, window)
    except (experiment.ConfigError, ValueError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for name, rows in results.items():
        print(f"sql check {name}: " + (f"{len(rows):,} disagreeing row(s)" if len(rows) else "agrees"))
        if len(rows):
            print(rows.head(SHOWN).to_string(index=False))
    failed = sum(len(rows) > 0 for rows in results.values())
    print("sql check: " + (f"{failed} of {len(results)} checks disagree" if failed else
                           f"all {len(results)} checks agree"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
