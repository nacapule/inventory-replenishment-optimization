#!/usr/bin/env python3
"""Check the published reconciliation, reversal pairs and weekly sales in SQLite.

    python src/sqlcheck.py [--config FILE] [--input XLSX] [--output DIR]

Classifies the workbook's rows, loads the ledger's row fields, the configuration and three
published files (reconciliation.csv, reversal_pairs.csv and weekly_sales.csv from the
output folder) into an in-memory SQLite database, and runs sql/reconciliation.sql, which
works out the roles, the pairing rule, the study weeks, the cohort and the weekly sums
again. Prints each check's result; the exit status is 1 when any check disagrees and 2 on
an error.
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
FILES = {  # published file -> its columns; numbers and times are parsed exactly, blanks become NULL
    "reconciliation.csv": {"sheet": "text", "role": "text", "rows": "number", "units": "number", "value": "number"},
    "reversal_pairs.csv": {
        "sku": "text", "customer_id": "number", "price": "number", "units": "number", "code_class": "text",
        "sale_sheet": "text", "sale_row": "number", "sale_invoice": "text", "sale_time": "time",
        "sale_country": "text", "credit_sheet": "text", "credit_row": "number", "credit_invoice": "text",
        "credit_time": "time", "credit_country": "text", "lag_minutes": "number", "prompt": "text"},
    "weekly_sales.csv": {"week_start": "text", "period": "text", "closure": "text", "sku": "text",
                         "units": "number", "units_at_week_close": "number", "revenue": "number"},
}
SETTINGS = ("country", "skus", "min_active_weeks", "selection_weeks", "evaluation_weeks")
SHOWN = 10  # disagreeing rows printed per check


def run_checks(ledger: pd.DataFrame, exports, config: experiment.Config) -> dict[str, pd.DataFrame]:
    """Each check's disagreeing rows by check name, in file order; all empty means agreement."""
    with contextlib.closing(sqlite3.connect(":memory:")) as db:
        load(db, ledger, Path(exports), config)
        setup, *parts = re.split(r"^-- check: (\w+)\n", SQL.read_text(encoding="utf-8"), flags=re.MULTILINE)
        db.executescript(setup)
        return {name: pd.read_sql_query(query, db) for name, query in zip(parts[::2], parts[1::2])}


def load(db: sqlite3.Connection, ledger: pd.DataFrame, exports: Path, config: experiment.Config):
    fields = pd.DataFrame(index=ledger.index)
    for name in FIELDS:
        column = ledger[name]
        if column.dtype == bool:
            fields[name] = column.astype(int)
        elif isinstance(column.dtype, pd.CategoricalDtype):
            fields[name] = column.astype(object).where(column.notna(), None)
        else:
            fields[name] = column
    fields["t"] = nanoseconds(ledger["timestamp"])
    fields.to_sql("ledger", db, index=False)
    for name, columns in FILES.items():
        frame = pd.read_csv(exports / name, dtype=str, keep_default_na=False)
        missing = [column for column in columns if column not in frame]
        if missing:
            raise ValueError(f"{exports / name} lacks columns: {', '.join(missing)}")
        for column, kind in columns.items():
            if kind == "number":
                frame[column] = [float(text) if text else None for text in frame[column]]
            elif kind == "time":
                frame[column] = nanoseconds(pd.to_datetime(frame[column].where(frame[column].ne("")), format="ISO8601"))
        frame.to_sql(name.removesuffix(".csv"), db, index=False)
    settings = {name: getattr(config, name) for name in SETTINGS}
    settings["window_ns"] = pd.Timedelta(config.reversal_hours, "h").value
    pd.DataFrame([settings]).to_sql("params", db, index=False)


def nanoseconds(stamps: pd.Series) -> pd.Series:
    """Timestamps as whole nanoseconds since 1970, missing ones as NULL."""
    values = pd.Series(stamps.to_numpy("datetime64[ns]").astype("int64"), index=stamps.index, dtype="Int64")
    return values.mask(stamps.isna())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check published files against the ledger in SQLite.")
    parser.add_argument("--config", type=Path, default=Path("configs/published.toml"))
    parser.add_argument("--input", type=Path, default=Path("data/raw/online_retail_II.xlsx"))
    parser.add_argument("--output", type=Path, default=Path("exports"))
    args = parser.parse_args(argv)
    try:
        config = experiment.load_config(args.config)
        ledger = data.classify(data.read_workbook(args.input), window=pd.Timedelta(config.reversal_hours, "h"))
        results = run_checks(ledger, args.output, config)
    except (experiment.ConfigError, ValueError, FileNotFoundError, sqlite3.Error, pd.errors.DatabaseError) as error:
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
