"""Read, classify and aggregate the Online Retail II invoice lines.

Every source row keeps its sheet and spreadsheet row number and receives exactly
one role. A sale is a positive, priced, non-credit invoice line. A sale and a
credit form a reversal pair when the customer is known and equal, the
case-normalized stock code, unit price and quantity are equal, and the credit is
strictly later; each credit takes the most recent unused such sale. A pair whose
credit follows within the window (24 hours by default) is a prompt reversal.
Removing a pair from sales takes effect at the credit's timestamp (`known_at`),
so sales as known at a cutoff never use a later credit. Other credits stay in
the credit ledger and are never netted into sales.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd

SHEETS = ("Year 2009-2010", "Year 2010-2011")
OVERLAP_ROWS = 22_523
UNION_ROWS = 1_044_848
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "code_registry.csv"
WINDOW = pd.Timedelta(24, "h")
WEEK = pd.Timedelta(7, "D")
NEVER = np.iinfo(np.int64).max
COLUMNS = {
    "invoice": "invoice", "stockcode": "stock_code", "description": "description",
    "quantity": "quantity", "invoicedate": "timestamp", "price": "price",
    "customer_id": "customer_id", "country": "country",
}
# Roles in priority order: each row takes the first that applies.
ROLES = (
    "overlap", "accounting_invoice", "invalid", "prompt_reversal_credit", "ledger_credit",
    "stock_adjustment", "zero_price", "prompt_reversal_sale", "non_merchandise",
    "quarantined", "merchandise_sale",
)
LAG_BUCKETS = [
    (pd.Timedelta(1, "h"), "up to 1 hour"), (pd.Timedelta(24, "h"), "1 to 24 hours"),
    (pd.Timedelta(7, "D"), "1 to 7 days"), (pd.Timedelta(28, "D"), "7 to 28 days"),
    (pd.Timedelta.max, "over 28 days"),
]


@dataclass(frozen=True)
class DataRules:
    """Which source lines count as sales.

    reversals: "prompt" removes prompt reversal pairs, "all_exact" removes every
    exactly matched pair, "none" removes nothing; a removal applies from its
    credit's timestamp. registry: drop registry codes (excluded and quarantined)
    and accounting (A) invoices. normalize_case: key sales by the uppercased code
    rather than the code as written.
    """

    reversals: str = "prompt"
    registry: bool = True
    normalize_case: bool = True

    def __post_init__(self):
        if self.reversals not in ("none", "prompt", "all_exact"):
            raise ValueError(f"unknown reversals rule {self.reversals!r}")
        for name in ("registry", "normalize_case"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be true or false")


PRIMARY_RULES = DataRules()
ORIGINAL_RULES = DataRules(reversals="none", registry=False, normalize_case=False)
ALL_EXACT_RULES = DataRules(reversals="all_exact")


def read_workbook(path, overlap_rows=OVERLAP_ROWS, union_rows=UNION_ROWS) -> pd.DataFrame:
    """Read both sheets once and mark the older sheet's copy of the overlap."""
    sheets = pd.read_excel(path, sheet_name=list(SHEETS), engine="openpyxl")
    first, second = (_source_frame(sheets[name], name) for name in SHEETS)
    return combine_sheets(first, second, overlap_rows, union_rows)


def _source_frame(frame: pd.DataFrame, sheet: str) -> pd.DataFrame:
    names = {column: COLUMNS[key] for column in frame.columns
             if (key := str(column).strip().lower().replace(" ", "_")) in COLUMNS}
    missing = sorted(set(COLUMNS.values()) - set(names.values()))
    if missing:
        raise ValueError(f"sheet {sheet!r} lacks columns: {', '.join(missing)}")
    data = frame.rename(columns=names)[list(COLUMNS.values())].reset_index(drop=True)
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce", format="mixed")
    data.insert(0, "sheet", sheet)
    data.insert(1, "source_row", np.arange(len(data)) + 2)
    return data


def combine_sheets(first, second, overlap_rows=None, union_rows=None) -> pd.DataFrame:
    """Keep the older sheet's rows dated before the newer sheet starts, plus all of it.

    The dropped block must equal, as a multiset of rows, the newer sheet's rows up
    to the older sheet's last timestamp. Both sheets' rows are returned; `overlap`
    marks the dropped copy.
    """
    overlap = first["timestamp"].ge(second["timestamp"].min())
    twin = second.loc[second["timestamp"].le(first["timestamp"].max())]
    if _multiset(first.loc[overlap]) != _multiset(twin):
        raise ValueError("the sheets' overlapping rows differ")
    if overlap_rows is not None and int(overlap.sum()) != overlap_rows:
        raise ValueError(f"expected {overlap_rows:,} overlapping rows, found {int(overlap.sum()):,}")
    combined = pd.concat([first.assign(overlap=overlap), second.assign(overlap=False)], ignore_index=True)
    if union_rows is not None and int((~combined["overlap"]).sum()) != union_rows:
        raise ValueError(f"expected {union_rows:,} combined rows, found {int((~combined['overlap']).sum()):,}")
    return combined


def _multiset(frame: pd.DataFrame) -> Counter:
    """Rows as comparable values: numbers as floats, other cells as text, blanks as None."""
    canonical = pd.DataFrame({name: _value(frame[name]) for name in COLUMNS.values()})
    return Counter(map(tuple, canonical.where(canonical.notna(), None).itertuples(index=False, name=None)))


def _value(cells: pd.Series) -> pd.Series:
    if cells.name == "timestamp":
        return cells.astype(object)
    text = _text(cells).astype(object)
    if cells.name in ("invoice", "stock_code", "description", "country"):
        return text
    numbers = pd.to_numeric(cells, errors="coerce").astype(float)
    return numbers.astype(object).where(numbers.notna(), text)


def load_registry(path=REGISTRY_PATH) -> pd.DataFrame:
    registry = pd.read_csv(path, dtype=str, keep_default_na=False).set_index("code")
    if not registry.index.is_unique or (registry.index != registry.index.str.strip().str.upper()).any():
        raise ValueError("registry codes must be unique, stripped and uppercase")
    if not registry["action"].isin(["exclude", "quarantine"]).all() or registry["class"].eq("").any():
        raise ValueError("every registry code needs a class and an exclude or quarantine action")
    return registry


def _text(values: pd.Series) -> pd.Series:
    """Source cells as text; whole-number floats lose their '.0'."""

    def one(value):
        if isinstance(value, str):
            return value
        if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
            return None
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    return pd.Series([one(value) for value in values.tolist()], index=values.index, dtype="string")


def classify(source: pd.DataFrame, window=WINDOW, registry=None) -> pd.DataFrame:
    """Normalize the source rows and give each one role (the ledger, one row per source row).

    `source` has sheet, source_row, the eight source columns and optionally
    overlap. Ledger columns: identity (sheet, source_row, overlap), normalized
    fields (invoice, stock_code as written, sku stripped and uppercased,
    description, quantity Int64, price, timestamp, customer_id Int64 or missing,
    country), flags (valid, credit, accounting, code_class, code_action), role
    and reason, and the pairing: pair_row (the other row of an exact pair),
    known_at (its credit's timestamp), lag, prompt (lag within the window) and,
    on later credits, reinvoice_row (an equal sale up to the window after it).
    """
    registry = load_registry() if registry is None else registry
    source = source.reset_index(drop=True)
    rows = pd.DataFrame({"sheet": source["sheet"].astype(str), "source_row": source["source_row"].astype("int64")})
    rows.index.name = "row_id"
    rows["overlap"] = source["overlap"].astype(bool) if "overlap" in source else False
    rows["invoice"] = _text(source["invoice"]).str.strip()
    rows["stock_code"] = _text(source["stock_code"])
    rows["sku"] = rows["stock_code"].str.strip().str.upper()
    rows["description"] = _text(source["description"]).str.strip().replace("", pd.NA)
    quantity = pd.to_numeric(source["quantity"], errors="coerce").astype(float)
    whole = np.isfinite(quantity) & quantity.eq(quantity.round())
    rows["quantity"] = quantity.where(whole).astype("Int64")
    price = pd.to_numeric(source["price"], errors="coerce").astype(float)
    rows["price"] = price
    rows["timestamp"] = pd.to_datetime(source["timestamp"], errors="coerce", format="mixed").astype("datetime64[ns]")
    customer = pd.to_numeric(source["customer_id"], errors="coerce")
    if (customer.isna() & source["customer_id"].notna()).any() or (customer % 1).fillna(0).ne(0).any():
        raise ValueError("customer IDs must be whole numbers")
    rows["customer_id"] = customer.astype("Int64")
    rows["country"] = _text(source["country"]).str.strip()

    prefix = rows["invoice"].str.upper().str[:1]
    credit = prefix.eq("C").fillna(False).to_numpy(bool)
    accounting = prefix.eq("A").fillna(False).to_numpy(bool)
    problems = [
        (rows["timestamp"].isna(), "missing_timestamp"), (rows["invoice"].fillna("").eq(""), "missing_invoice"),
        (rows["sku"].fillna("").eq(""), "missing_stock_code"), (rows["country"].fillna("").eq(""), "missing_country"),
        (quantity.isna(), "missing_quantity"), (~np.isfinite(quantity), "nonfinite_quantity"),
        (~whole, "fractional_quantity"), (quantity.eq(0), "zero_quantity"),
        (price.isna(), "missing_price"), (~np.isfinite(price), "nonfinite_price"), (price.lt(0), "negative_price"),
    ]
    invalid_reason = np.select([np.asarray(mask, bool) for mask, _ in problems], [r for _, r in problems], "")
    valid = invalid_reason == ""
    rows["valid"] = valid
    rows["credit"], rows["accounting"] = credit, accounting
    rows["code_class"] = rows["sku"].map(registry["class"]).fillna("merchandise")
    rows["code_action"] = rows["sku"].map(registry["action"]).fillna("keep")

    q, p = quantity.to_numpy(), price.to_numpy()
    usable = valid & ~rows["overlap"].to_numpy() & rows["customer_id"].notna().to_numpy() & (p > 0)
    sales, credits, reinvoices = _match(rows, usable & ~credit & ~accounting & (q > 0), usable & credit & (q < 0), window)
    lag = rows["timestamp"].to_numpy()[credits] - rows["timestamp"].to_numpy()[sales]
    rows["pair_row"] = pd.array([pd.NA] * len(rows), dtype="Int64")
    rows.loc[sales, "pair_row"], rows.loc[credits, "pair_row"] = credits, sales
    rows["known_at"] = pd.Series(pd.NaT, index=rows.index, dtype="datetime64[ns]")
    rows.loc[sales, "known_at"] = rows.loc[credits, "known_at"] = rows["timestamp"].to_numpy()[credits]
    rows["lag"] = pd.Series(pd.NaT, index=rows.index, dtype="timedelta64[ns]")
    rows.loc[sales, "lag"] = rows.loc[credits, "lag"] = lag
    rows["prompt"] = rows["lag"].le(window).to_numpy()
    rows["reinvoice_row"] = pd.array([pd.NA] * len(rows), dtype="Int64")
    flagged = np.array([[c, s] for c, s in reinvoices.items() if not rows.at[c, "prompt"]], dtype=int).reshape(-1, 2)
    rows.loc[flagged[:, 0], "reinvoice_row"] = flagged[:, 1]

    paired, prompt = rows["pair_row"].notna().to_numpy(), rows["prompt"].to_numpy()
    overlap, action = rows["overlap"].to_numpy(), rows["code_action"].to_numpy()
    roles = np.select(
        [overlap, accounting, ~valid, credit & prompt, credit, q < 0, p == 0, prompt & paired,
         action == "exclude", action == "quarantine"],
        list(ROLES[:-1]), ROLES[-1])
    credit_reason = np.select(
        [paired, q > 0, rows["customer_id"].isna().to_numpy(), ~(p > 0)],
        ["later_exact_match", "not_negative", "missing_customer", "nonpositive_price"], "no_earlier_equal_sale")
    reason = np.select(
        [roles == "invalid", roles == "ledger_credit", np.isin(roles, ["non_merchandise", "quarantined"])],
        [invalid_reason, credit_reason, rows["code_class"].to_numpy(str)], "")
    rows["role"] = pd.Categorical(roles, categories=ROLES)
    rows["reason"] = reason
    for column in ("sheet", "invoice", "stock_code", "sku", "description", "country", "code_class",
                   "code_action", "reason"):
        rows[column] = rows[column].astype("category")
    return rows


def _match(rows, sale_ok, credit_ok, window):
    """Pair each credit with the most recent unused strictly earlier sale of its key.

    Returns sale and credit row positions of every pair and, for each paired
    credit, the earliest same-key sale at most `window` after it (a re-invoice).
    """
    keys = pd.DataFrame({
        "customer": rows["customer_id"], "sku": pd.factorize(rows["sku"])[0], "price": rows["price"],
        "units": rows["quantity"].abs(),
    }).loc[sale_ok | credit_ok]
    group = keys.groupby(["customer", "sku", "price", "units"], sort=False).ngroup().to_numpy()
    is_sale = sale_ok[keys.index.to_numpy()]
    wanted = np.zeros(group.max() + 1 if len(group) else 0, bool)
    wanted[group[~is_sale]] = True
    keep = wanted[group]
    position = keys.index.to_numpy()[keep]
    group, is_sale = group[keep], is_sale[keep]
    stamp = rows["timestamp"].to_numpy("datetime64[ns]")[position].astype("int64")
    order = np.lexsort((position, is_sale, stamp, group))
    group, is_sale, stamp, position = group[order], is_sale[order], stamp[order], position[order]
    sales, credits, stack, current = [], [], [], None
    for g, sale, row in zip(group.tolist(), is_sale.tolist(), position.tolist()):
        if g != current:
            stack, current = [], g
        if sale:
            stack.append(row)
        elif stack:
            sales.append(stack.pop())
            credits.append(row)
    following, upcoming = np.full(len(group), -1), -1
    for i in range(len(group) - 1, -1, -1):
        if i + 1 < len(group) and group[i + 1] != group[i]:
            upcoming = -1
        following[i] = upcoming
        if is_sale[i]:
            upcoming = i
    reinvoices, at = {}, {row: i for i, row in enumerate(position.tolist())}
    for row in credits:
        j = following[at[row]]
        if j >= 0 and stamp[j] - stamp[at[row]] <= window.value:
            reinvoices[row] = int(position[j])
    return np.array(sales, dtype=int), np.array(credits, dtype=int), reinvoices


def _monday(stamps):
    if isinstance(stamps, pd.Timestamp):
        return stamps.normalize() - pd.Timedelta(stamps.weekday(), "D")
    return stamps.dt.normalize() - pd.to_timedelta(stamps.dt.weekday, unit="D")


def calendar(ledger: pd.DataFrame) -> pd.DataFrame:
    """Monday-start weeks spanning the source, with completeness and closure flags.

    A week is complete when its seven days lie within the first and last source
    dates; a closure week has no source row in any country.
    """
    stamps = ledger.loc[~ledger["overlap"] & ledger["timestamp"].notna(), ["timestamp", "invoice"]]
    if stamps.empty:
        raise ValueError("the ledger has no dated source rows")
    first, last = stamps["timestamp"].min(), stamps["timestamp"].max()
    weeks = pd.date_range(_monday(first), _monday(last), freq="7D", name="week_start")
    activity = stamps.groupby(_monday(stamps["timestamp"])).agg(
        rows=("invoice", "size"), invoices=("invoice", "nunique")).reindex(weeks, fill_value=0)
    return pd.DataFrame({
        "week_start": weeks,
        "complete": (weeks >= first.normalize()) & (weeks + pd.Timedelta(6, "D") <= last.normalize()),
        "closure": activity["rows"].to_numpy() == 0,
        "rows": activity["rows"].to_numpy(), "invoices": activity["invoices"].to_numpy(),
    })


def _sales_mask(ledger: pd.DataFrame, rules: DataRules) -> pd.Series:
    mask = ledger["valid"] & ~ledger["overlap"] & ~ledger["credit"] & ledger["quantity"].gt(0) & ledger["price"].gt(0)
    if rules.registry:
        mask &= ledger["code_action"].eq("keep") & ~ledger["accounting"]
    return mask.fillna(False).astype(bool)


class SalesPanel:
    """One country's sales lines under one set of rules, ready for many cutoffs.

    A cutoff is a timestamp: a removal applies when its credit is recorded
    strictly before it (cutoff=None applies every removal). Weeks are the
    calendar's Monday starts; windows are [start, end) on line timestamps.
    """

    def __init__(self, ledger: pd.DataFrame, rules: DataRules, country: str):
        self.rules, self.country = rules, country
        self.weeks = pd.DatetimeIndex(calendar(ledger)["week_start"], name="week_start")
        keep = _sales_mask(ledger, rules) & ledger["country"].eq(country).fillna(False)
        if rules.normalize_case:
            key = ledger["sku"]
        else:
            key = ledger["stock_code"].astype(str).str.strip()
        lines = ledger.loc[keep, ["timestamp", "stock_code", "invoice", "customer_id", "description", "price",
                                  "known_at"]].copy()
        lines.insert(1, "sku", key[keep].astype(str))
        lines[["stock_code", "invoice"]] = lines[["stock_code", "invoice"]].astype(str)
        lines["description"] = lines["description"].astype("string")
        lines["quantity"] = ledger.loc[keep, "quantity"].astype("int64")
        removable = ledger.loc[keep, "pair_row"].notna()
        if rules.reversals == "prompt":
            removable &= ledger.loc[keep, "prompt"]
        elif rules.reversals == "none":
            removable &= False
        lines["known_at"] = lines["known_at"].where(removable)
        lines = lines.sort_values("timestamp", kind="stable").reset_index(drop=True)
        self.lines = lines
        self.skus = pd.Index(sorted(lines["sku"].unique()), name="sku")
        self._sku = self.skus.get_indexer(lines["sku"])
        self._week = ((_monday(lines["timestamp"]) - self.weeks[0]) // WEEK).to_numpy()
        self._units = lines["quantity"].to_numpy()
        self._revenue = self._units * lines["price"].to_numpy()
        self._stamp = lines["timestamp"].to_numpy("datetime64[ns]").astype("int64")
        known = lines["known_at"].to_numpy("datetime64[ns]")
        self._known = np.where(np.isnat(known), NEVER, known.astype("int64"))
        self._cell = self._week * len(self.skus) + self._sku
        self._group = lines.groupby([self._week, lines["invoice"], self._sku], sort=False).ngroup().to_numpy()
        first = pd.Series(np.arange(len(lines))).groupby(self._group).first().to_numpy()
        self._group_sku, self._group_cell = self._sku[first], self._cell[first]
        self._positions = {self.skus[i]: where for i, where in pd.Series(self._sku).groupby(self._sku).indices.items()}

    def _cutoff(self, cutoff) -> int:
        return NEVER if cutoff is None else pd.Timestamp(cutoff).as_unit("ns").value

    def _kept(self, cutoff) -> np.ndarray:
        return self._known >= self._cutoff(cutoff)

    def _cells(self, cutoff, caps):
        """Units and revenue per (week, SKU) cell as flat arrays."""
        size, kept = len(self.weeks) * len(self.skus), self._kept(cutoff)
        if caps is None:
            units = np.bincount(self._cell[kept], self._units[kept], minlength=size)
            revenue = np.bincount(self._cell[kept], self._revenue[kept], minlength=size)
            return np.rint(units).astype("int64"), revenue
        group_units, group_revenue = self._invoice_totals(kept)
        limit = pd.Series(caps, dtype=float).reindex(self.skus).fillna(np.inf).to_numpy()
        if (limit < 0).any() or (limit[np.isfinite(limit)] % 1 != 0).any():
            raise ValueError("caps must be whole numbers of units, at least zero")
        capped = np.minimum(group_units, limit[self._group_sku])
        scale = np.divide(capped, group_units, out=np.zeros_like(capped), where=group_units > 0)
        units = np.bincount(self._group_cell, capped, minlength=size)
        revenue = np.bincount(self._group_cell, group_revenue * scale, minlength=size)
        return np.rint(units).astype("int64"), revenue

    def _invoice_totals(self, kept):
        """Units and revenue of each invoice-SKU group (lines of one invoice and SKU summed)."""
        size = self._group_sku.size
        return (np.rint(np.bincount(self._group[kept], self._units[kept], minlength=size)),
                np.bincount(self._group[kept], self._revenue[kept], minlength=size))

    def matrix(self, cutoff=None, skus=None, caps=None) -> pd.DataFrame:
        """Weeks x SKUs integer sales, zeros included, as known at the cutoff.

        caps (SKU -> units) limits each invoice-SKU total before the weekly sums;
        SKUs without a cap are left as they are, and capped revenue scales with units.
        """
        units, _ = self._cells(cutoff, caps)
        frame = pd.DataFrame(units.reshape(len(self.weeks), len(self.skus)), index=self.weeks, columns=self.skus)
        return frame if skus is None else frame.reindex(columns=pd.Index(skus, name="sku"), fill_value=0)

    def weekly(self, cutoff=None, caps=None) -> pd.DataFrame:
        """Long frame (week_start, sku, units, revenue) of non-zero SKU-weeks."""
        units, revenue = self._cells(cutoff, caps)
        cells = np.flatnonzero(units)
        return pd.DataFrame({
            "week_start": self.weeks[cells // len(self.skus)], "sku": self.skus[cells % len(self.skus)],
            "units": units[cells], "revenue": revenue[cells],
        })

    def bulk_caps(self, start=None, end=None, cutoff=None, quantile="0.99") -> pd.Series:
        """Each SKU's rounded-up quantile of invoice-SKU quantities in [start, end).

        The quantile interpolates linearly between order statistics (pandas'
        default) and is computed exactly, so a whole-number quantile is never
        pushed up by floating-point error before rounding up.
        """
        share = Fraction(str(quantile))
        if not 0 <= share <= 1:
            raise ValueError("quantile must be between 0 and 1")
        group_units, _ = self._invoice_totals(self._in_window(start, end, cutoff))
        inside = group_units > 0
        sku, values = self._group_sku[inside], group_units[inside].astype("int64")
        order = np.lexsort((values, sku))
        sku, values = sku[order], values[order]
        firsts = np.flatnonzero(np.r_[True, sku[1:] != sku[:-1]]) if sku.size else np.empty(0, int)
        counts = np.diff(np.r_[firsts, sku.size])
        step = (counts - 1) * share.numerator
        low = firsts + step // share.denominator
        high = np.minimum(low + 1, firsts + counts - 1)
        gap = (step % share.denominator) * (values[high] - values[low])
        caps = values[low] - (-gap // share.denominator)
        return pd.Series(caps, index=pd.Index(self.skus[sku[firsts]], name="sku"), name="cap", dtype="int64")

    def prices(self, start=None, end=None, cutoff=None, skus=None) -> pd.Series:
        """Median unit price of each SKU's kept lines in [start, end)."""
        low, high, threshold = _stamp(start, -NEVER), _stamp(end, NEVER), self._cutoff(cutoff)
        price, result = self.lines["price"].to_numpy(), {}
        for sku in self.skus if skus is None else skus:
            where = self._positions.get(sku, np.empty(0, int))
            stamps = self._stamp[where]
            where = where[np.searchsorted(stamps, low):np.searchsorted(stamps, high)]
            where = where[self._known[where] >= threshold]
            result[sku] = float(np.median(price[where])) if where.size else math.nan
        return pd.Series(result, dtype=float, name="price").rename_axis("sku")

    def _in_window(self, start=None, end=None, cutoff=None) -> np.ndarray:
        return self._kept(cutoff) & (self._stamp >= _stamp(start, -NEVER)) & (self._stamp < _stamp(end, NEVER))

    def window(self, start=None, end=None, cutoff=None) -> pd.DataFrame:
        """Kept lines in [start, end) as known at the cutoff."""
        return self.lines.loc[self._in_window(start, end, cutoff)]

    def concentration(self, start=None, end=None, cutoff=None, skus=None) -> pd.DataFrame:
        """Anonymous, top-customer and top-invoice shares of each SKU's units."""
        lines = self.window(start, end, cutoff)
        if skus is not None:
            lines = lines.loc[lines["sku"].isin(list(skus))]
        units = lines.groupby("sku")["quantity"].sum()
        named = lines.loc[lines["customer_id"].notna()]
        customers = named.groupby(["sku", "customer_id"])["quantity"].sum()
        invoices = lines.groupby(["sku", lines["invoice"]])["quantity"].sum()
        top_customer = customers.groupby(level="sku").idxmax().map(lambda key: key[1])
        top_invoice = invoices.groupby(level="sku").idxmax().map(lambda key: key[1])
        frame = pd.DataFrame({
            "units": units,
            "customers": customers.groupby(level="sku").size(),
            "invoices": invoices.groupby(level="sku").size(),
            "anonymous_share": lines.loc[lines["customer_id"].isna()].groupby("sku")["quantity"].sum(),
            "top_customer": top_customer.astype("Int64"),
            "top_customer_share": customers.groupby(level="sku").max(),
            "top_invoice": top_invoice,
            "top_invoice_share": invoices.groupby(level="sku").max(),
        })
        frame[["customers", "invoices"]] = frame[["customers", "invoices"]].fillna(0).astype("int64")
        for column in ("anonymous_share", "top_customer_share", "top_invoice_share"):
            frame[column] = frame[column].fillna(0) / frame["units"]
        frame = frame.rename_axis("sku")
        return frame if skus is None else frame.reindex(pd.Index(skus, name="sku"))

    def descriptions(self, start=None, end=None, skus=None) -> pd.Series:
        """Modal description per SKU over the window, for display only."""
        lines = self.window(start, end)
        if skus is not None:
            lines = lines.loc[lines["sku"].isin(list(skus))]
        modal = lines.groupby("sku")["description"].agg(_representative_description)
        index = self.skus if skus is None else pd.Index(skus, name="sku")
        return modal.reindex(index).fillna("Unknown item").rename("description")

    def aliases(self, skus=None) -> pd.DataFrame:
        """Source spellings of every SKU written more than one way."""
        lines = self.lines if skus is None else self.lines.loc[self.lines["sku"].isin(list(skus))]
        table = lines.groupby(["sku", "stock_code"]).agg(
            rows=("quantity", "size"), units=("quantity", "sum")).reset_index()
        return table.loc[table.groupby("sku")["stock_code"].transform("size").gt(1)].reset_index(drop=True)

    def description_drift(self, skus=None) -> pd.DataFrame:
        """Descriptions of every SKU recorded under more than one, with dates."""
        lines = self.lines if skus is None else self.lines.loc[self.lines["sku"].isin(list(skus))]
        lines = lines.loc[lines["description"].notna()]
        table = lines.groupby(["sku", "description"]).agg(
            rows=("quantity", "size"), units=("quantity", "sum"),
            first_seen=("timestamp", "min"), last_seen=("timestamp", "max")).reset_index()
        return table.loc[table.groupby("sku")["description"].transform("size").gt(1)].reset_index(drop=True)

    def unusual_codes(self, start=None, end=None) -> pd.DataFrame:
        """Kept codes that are not digits plus an optional letter suffix."""
        lines = self.window(start, end)
        lines = lines.loc[~lines["sku"].str.fullmatch(r"\d+[A-Za-z]*")]
        table = lines.groupby("sku").agg(rows=("quantity", "size"), units=("quantity", "sum"))
        table["description"] = lines.groupby("sku")["description"].agg(_representative_description)
        return table.reset_index()


def _stamp(value, default: int) -> int:
    return default if value is None else pd.Timestamp(value).as_unit("ns").value


def _representative_description(values: pd.Series) -> str:
    usable = values.astype("string").fillna("").str.strip()
    usable = usable[usable.ne("")]
    if usable.empty:
        return "Unknown item"
    modes = usable.mode()
    return str(modes.iloc[0] if not modes.empty else usable.iloc[-1])


def reconciliation(ledger: pd.DataFrame, country=None, by_reason=False) -> pd.DataFrame:
    """Rows, signed units and signed value by sheet and role; rows sum to the source."""
    rows = ledger if country is None else ledger.loc[ledger["country"].eq(country).fillna(False)]
    keys = ["sheet", "role"] + (["reason"] if by_reason else [])
    value = rows["quantity"].astype(float) * rows["price"]
    table = rows.assign(units=rows["quantity"].fillna(0), value=value.fillna(0.0)).groupby(
        keys, observed=True).agg(rows=("source_row", "size"), units=("units", "sum"), value=("value", "sum"))
    return table.reset_index().astype({"units": "int64"})


def bridge(ledger: pd.DataFrame, country: str) -> pd.DataFrame:
    """Accepted lines -> merchandise -> after prompt reversals -> complete weeks."""
    rows = ledger.loc[ledger["country"].eq(country).fillna(False)]
    accepted, merchandise = _sales_mask(rows, ORIGINAL_RULES), _sales_mask(rows, PRIMARY_RULES)
    kept = merchandise & ~(rows["pair_row"].notna() & rows["prompt"])
    weeks = calendar(ledger)
    complete = _monday(rows["timestamp"]).isin(weeks.loc[weeks["complete"], "week_start"])
    stages = [("accepted", accepted), ("merchandise", merchandise), ("after_prompt_reversals", kept),
              ("complete_weeks", kept & complete)]
    units, value = rows["quantity"].astype(float), rows["quantity"].astype(float) * rows["price"]
    return pd.DataFrame([
        {"stage": name, "rows": int(mask.sum()), "units": int(units[mask].sum()), "value": float(value[mask].sum())}
        for name, mask in stages])


def credit_summary(ledger: pd.DataFrame, country=None) -> pd.DataFrame:
    """Credit lines by matching status and lag bucket, with re-invoice candidates."""
    credits = ledger.loc[ledger["role"].isin(["prompt_reversal_credit", "ledger_credit"])]
    if country is not None:
        credits = credits.loc[credits["country"].eq(country).fillna(False)]
    status = np.where(credits["role"].eq("prompt_reversal_credit"), "prompt_reversal", credits["reason"].astype(str))
    bucket = pd.Series("unmatched", index=credits.index)
    for limit, label in reversed(LAG_BUCKETS):
        bucket[credits["lag"].le(limit)] = label
    units, reinvoiced = -credits["quantity"].astype(float), credits["reinvoice_row"].notna()
    table = pd.DataFrame({
        "status": status, "lag_bucket": bucket, "units": units, "value": units * credits["price"],
        "reinvoiced": reinvoiced, "reinvoiced_units": units.where(reinvoiced, 0.0),
    }).groupby(["status", "lag_bucket"], sort=False).agg(
        credits=("units", "size"), units=("units", "sum"), value=("value", "sum"),
        reinvoice_candidates=("reinvoiced", "sum"), reinvoiced_units=("reinvoiced_units", "sum"))
    return table.reset_index().astype({"units": "int64", "reinvoiced_units": "int64"})


def reversal_pairs(ledger: pd.DataFrame, prompt_only=True) -> pd.DataFrame:
    """Each reversal pair with both rows' identity, timestamps, lag and units."""
    sales = ledger.loc[ledger["pair_row"].notna() & ~ledger["credit"]]
    if prompt_only:
        sales = sales.loc[sales["prompt"]]
    credits = ledger.loc[sales["pair_row"].astype("int64").to_numpy()]
    frame = pd.DataFrame({
        "sku": sales["sku"].astype(str).to_numpy(), "customer_id": sales["customer_id"].to_numpy(),
        "price": sales["price"].to_numpy(), "units": sales["quantity"].astype("int64").to_numpy(),
        "code_class": sales["code_class"].astype(str).to_numpy(),
        "sale_sheet": sales["sheet"].astype(str).to_numpy(), "sale_row": sales["source_row"].to_numpy(),
        "sale_invoice": sales["invoice"].astype(str).to_numpy(), "sale_time": sales["timestamp"].to_numpy(),
        "sale_country": sales["country"].astype(str).to_numpy(),
        "credit_sheet": credits["sheet"].astype(str).to_numpy(), "credit_row": credits["source_row"].to_numpy(),
        "credit_invoice": credits["invoice"].astype(str).to_numpy(), "credit_time": credits["timestamp"].to_numpy(),
        "credit_country": credits["country"].astype(str).to_numpy(),
        "lag_minutes": sales["lag"].dt.total_seconds().to_numpy() / 60, "prompt": sales["prompt"].to_numpy(),
    })
    return frame.sort_values(["credit_time", "sale_time", "sale_sheet", "sale_row"], ignore_index=True)


def registry_exclusions(ledger: pd.DataFrame, country=None) -> pd.DataFrame:
    """Sale lines the registry or the accounting-invoice rule removes, by code."""
    rows = ledger.loc[_sales_mask(ledger, ORIGINAL_RULES) & ~_sales_mask(ledger, PRIMARY_RULES)]
    if country is not None:
        rows = rows.loc[rows["country"].eq(country).fillna(False)]
    code_class = np.where(rows["accounting"], "accounting", rows["code_class"].astype(str))
    action = np.where(rows["accounting"], "exclude", rows["code_action"].astype(str))
    table = rows.assign(code_class=code_class, code_action=action, value=rows["quantity"].astype(float) * rows["price"])
    table = table.assign(sku=table["sku"].astype(str), description=table["description"].astype("string"))
    table = table.groupby(["sku", "code_class", "code_action"]).agg(
        rows=("quantity", "size"), units=("quantity", "sum"), value=("value", "sum"),
        description=("description", _representative_description))
    return table.reset_index().rename(columns={"sku": "code"}).astype({"units": "int64"})


def repeated_lines(ledger: pd.DataFrame) -> pd.DataFrame:
    """Excess copies of identical source rows, per sheet (all kept as recorded)."""
    fields = ["invoice", "stock_code", "description", "quantity", "timestamp", "price", "customer_id", "country"]
    result = []
    for sheet, rows in ledger.groupby("sheet", observed=True):
        repeated = rows.duplicated(fields)
        result.append({"sheet": sheet, "rows": len(rows), "repeated_rows": int(repeated.sum()),
                       "repeated_units": int(rows.loc[repeated, "quantity"].fillna(0).sum())})
    return pd.DataFrame(result)
