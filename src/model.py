"""Newsvendor costs, capacity allocation and the weekly stock simulation.

Each week a SKU starts with ``x`` units, sells ``min(D, x)`` of that week's sales ``D``
and loses the rest; leftover units are carried into the next week. With unit price
``price``, holding rate ``h`` per leftover unit-week and shortage rate ``p`` per lost
unit (both fractions of price), the week costs

    price * (h * (x - D)+  +  p * (D - x)+).

Against an empirical history of ``n`` integer weekly sales, the expected cost of one more
unit of stock is

    C(x + 1) - C(x) = price * ((h + p) * #{D <= x} / n - p),

which never decreases in ``x``: each SKU's cost curve is discrete convex. Under a shared
limit on start-of-week stock, giving units one at a time to the SKU whose next unit
lowers expected cost the most reaches the global optimum, and stopping at the first
marginal that is not negative gives the smallest optimal stock. The price does not change
the sign of a marginal, so that sign is decided exactly from integer counts and the rates
as fractions; identical histories therefore get identical stock at any price.

Every quantity is a non-negative integer number of units. Inputs are checked where they
enter: NaN, infinite, negative or fractional values are rejected with a clear error.
"""

from __future__ import annotations

import heapq
import math
import numbers
from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Callable, Mapping, Sequence

import numpy as np

Policy = Callable[[int, dict[str, int]], "Mapping[str, int] | Sequence[int]"]

_RECORD_FIELDS = ("opening", "ordered", "start", "sales", "covered", "lost", "closing",
                  "holding_cost", "shortage_cost")


# Input checks ---------------------------------------------------------------------------


def _rate(value: object, name: str) -> Fraction:
    """A finite non-negative rate as an exact fraction; a float is read as the decimal it
    prints as (0.05 is 1/20), which is the value written in a configuration file."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, got {value!r}")
    try:
        if isinstance(value, (numbers.Rational, Decimal, str)):
            rate = Fraction(value)
        elif isinstance(value, numbers.Real):
            number = float(value)
            if not math.isfinite(number):
                raise ValueError
            rate = Fraction(repr(number))
        else:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} must be a finite number, got {value!r}") from None
    if rate < 0:
        raise ValueError(f"{name} must be non-negative, got {value!r}")
    return rate


def _count(value: object, name: str) -> int:
    """A non-negative whole number of units."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
    if isinstance(value, numbers.Integral):
        result = int(value)
    else:
        number = float(value)
        if not (math.isfinite(number) and number.is_integer()):
            raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
        result = int(number)
    if result < 0:
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
    return result


def _capacity(value: object) -> int | None:
    return None if value is None else _count(value, "capacity")


def _units(values: object, name: str) -> np.ndarray:
    """An array of non-negative integer units (integral floats are accepted)."""
    array = np.asarray(values)
    if array.dtype.kind in "bUSV":
        raise ValueError(f"{name} must contain numbers of units")
    if array.dtype.kind not in "iuf":
        try:
            array = array.astype(np.float64)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must contain numbers of units") from None
    if array.dtype.kind == "f":
        if not np.isfinite(array).all():
            raise ValueError(f"{name} contains NaN or infinite values")
        if not (array == np.trunc(array)).all():
            raise ValueError(f"{name} contains fractional units")
    if array.size and array.min() < 0:
        raise ValueError(f"{name} contains negative units")
    if array.size and array.max() > 2**53:
        raise ValueError(f"{name} contains values too large to count exactly")
    return array.astype(np.int64)


def _samples(values: object, name: str) -> np.ndarray:
    array = _units(values, name)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty sequence of weekly units")
    return array


def _sku_keys(mapping: object, name: str) -> list[str]:
    if not isinstance(mapping, Mapping):
        raise ValueError(f"{name} must be a mapping from SKU to values")
    keys = list(mapping)
    for key in keys:
        if not isinstance(key, str):
            raise ValueError(f"{name} keys must be SKU strings, got {key!r}")
    return keys


def _require_keys(mapping: Mapping, skus: Sequence[str], name: str) -> None:
    if not isinstance(mapping, Mapping):
        raise ValueError(f"{name} must be a mapping from SKU to values")
    if set(mapping) != set(skus):
        missing = sorted(set(skus) - set(mapping), key=str)
        extra = sorted(set(mapping) - set(skus), key=str)
        raise ValueError(f"{name} keys must match the SKUs (missing {missing}, extra {extra})")


def _quantities(mapping: object, name: str) -> dict[str, int]:
    return {sku: _count(mapping[sku], f"{name}[{sku!r}]") for sku in _sku_keys(mapping, name)}


def _floors(floors: Mapping[str, int] | None, skus: Sequence[str]) -> dict[str, int]:
    if floors is None:
        return {sku: 0 for sku in skus}
    _require_keys(floors, skus, "floors")
    return {sku: _count(floors[sku], f"floors[{sku!r}]") for sku in skus}


def _sorted_history(values: object, sku: str) -> list[int]:
    return np.sort(_samples(values, f"history for {sku!r}")).tolist()


def _number(value: object, name: str, positive: bool) -> float:
    """A finite price (positive) or weight (non-negative)."""
    kind = "positive" if positive else "non-negative"
    if isinstance(value, bool) or not isinstance(value, (numbers.Real, Decimal)):
        raise ValueError(f"{name} must be a finite {kind} number, got {value!r}")
    number = float(value)
    if not (math.isfinite(number) and (number > 0 if positive else number >= 0)):
        raise ValueError(f"{name} must be a finite {kind} number, got {value!r}")
    return number


# Costs ----------------------------------------------------------------------------------


def critical_ratio(holding_rate: object, shortage_rate: object) -> Fraction:
    """p / (h + p), exactly."""
    holding, shortage = _rate(holding_rate, "holding_rate"), _rate(shortage_rate, "shortage_rate")
    if holding + shortage == 0:
        raise ValueError("holding_rate and shortage_rate cannot both be zero")
    return shortage / (holding + shortage)


def expected_cost(samples: object, quantity: object, holding: object, shortage: object) -> float:
    """Mean of holding * leftover + shortage * unmet over the sample weeks (absolute costs)."""
    values, stock = _samples(samples, "samples"), _count(quantity, "quantity")
    h, p = float(_rate(holding, "holding")), float(_rate(shortage, "shortage"))
    overage = np.maximum(stock - values, 0)
    underage = np.maximum(values - stock, 0)
    return float(np.mean(h * overage + p * underage))


def marginal_cost(samples: object, quantity: object, holding: object, shortage: object) -> float:
    """C(q + 1) - C(q) = (holding + shortage) * F(q) - shortage for integer samples."""
    values, stock = _samples(samples, "samples"), _count(quantity, "quantity")
    h, p = float(_rate(holding, "holding")), float(_rate(shortage, "shortage"))
    return (h + p) * float(np.mean(values <= stock)) - p


# Allocation -----------------------------------------------------------------------------


def optimize_capacity(
    histories: Mapping[str, Sequence[int]],
    prices: Mapping[str, float] | None,
    holding_rate: object,
    shortage_rate: object,
    capacity: int | None,
    floors: Mapping[str, int] | None = None,
) -> dict[str, int]:
    """Start-of-week stock per SKU minimizing expected price-weighted cost.

    ``histories`` maps each SKU to its weekly sales samples; ``prices`` maps each SKU to
    its unit price (``None`` weighs every SKU equally). Holding and shortage cost per unit
    are ``price * holding_rate`` and ``price * shortage_rate``. Stock starts at ``floors``
    (carried stock, default zero) and only the free space ``capacity - sum(floors)`` is
    allocated; ``capacity=None`` removes the limit and returns the smallest unconstrained
    optimum. Units go to the most negative price-weighted marginal first; equal marginals
    go to the SKU that sorts first. A SKU stops receiving units once its next marginal is
    not negative, a test made exactly from integer counts and the rates as fractions.
    Between consecutive sample values the marginal is flat, so such a run of units is
    taken in one step, with the same result as adding them one at a time.
    """
    skus = _sku_keys(histories, "histories")
    samples = {sku: _sorted_history(histories[sku], sku) for sku in skus}
    if prices is None:
        weights = {sku: 1.0 for sku in skus}
    else:
        _require_keys(prices, skus, "prices")
        weights = {sku: _number(prices[sku], f"prices[{sku!r}]", True) for sku in skus}
    allocation = _floors(floors, skus)
    limit = _capacity(capacity)
    free = None if limit is None else limit - sum(allocation.values())
    if free is not None and free < 0:
        raise ValueError(f"floors total {sum(allocation.values())} exceeds capacity {limit}")
    holding, shortage = _rate(holding_rate, "holding_rate"), _rate(shortage_rate, "shortage_rate")
    scale = math.lcm(holding.denominator, shortage.denominator)
    slope = int((holding + shortage) * scale)  # integers: marginal * scale * n / price
    offset = int(shortage * scale)  #           equals slope * #{D <= x} - offset * n

    def next_step(sku: str) -> tuple[float, str, int] | None:
        """The SKU's next marginal and how many units share it, or None if not negative."""
        values, level = samples[sku], allocation[sku]
        covered = bisect_right(values, level)
        excess = slope * covered - offset * len(values)
        if excess >= 0:
            return None
        # covered < n here; F, and with it the marginal, is flat up to the next sample.
        return weights[sku] * excess / (scale * len(values)), sku, values[covered] - level

    heap = [step for step in map(next_step, skus) if step is not None]
    heapq.heapify(heap)
    while heap and (free is None or free > 0):
        _, sku, length = heapq.heappop(heap)
        units = length if free is None else min(length, free)
        allocation[sku] += units
        if free is not None:
            free -= units
        step = next_step(sku)
        if step is not None:
            heapq.heappush(heap, step)
    return allocation


def newsvendor_targets(
    histories: Mapping[str, Sequence[int]], holding_rate: object, shortage_rate: object
) -> dict[str, int]:
    """Each SKU's smallest unconstrained optimum: the inverse empirical CDF at p / (h + p)."""
    return optimize_capacity(histories, None, holding_rate, shortage_rate, capacity=None)


def upper_quantile_targets(
    histories: Mapping[str, Sequence[int]], holding_rate: object, shortage_rate: object
) -> dict[str, int]:
    """The originally published rule: NumPy's ``higher`` quantile at the critical ratio,
    the sorted sample at zero-based index ceil((n - 1) * p / (h + p)), computed exactly.
    It can exceed the smallest optimum; kept to rerun the original design."""
    ratio = critical_ratio(holding_rate, shortage_rate)
    result = {}
    for sku in _sku_keys(histories, "histories"):
        values = _sorted_history(histories[sku], sku)
        result[sku] = values[math.ceil((len(values) - 1) * ratio)]
    return result


def proportional_allocation(weights: Mapping[str, float], capacity: int) -> dict[str, int]:
    """Split ``capacity`` in proportion to ``weights`` by largest remainder.

    The result sums to ``capacity`` unless every weight is zero. Equal remainders go to
    the key that comes first in ``weights``. Integer weights are apportioned exactly.
    """
    keys = _sku_keys(weights, "weights")
    limit = _count(capacity, "capacity")
    values = [weights[key] for key in keys]
    if all(isinstance(v, numbers.Integral) and not isinstance(v, bool) for v in values):
        counts = [_count(v, f"weights[{key!r}]") for key, v in zip(keys, values)]
        total = sum(counts)
        if total == 0 or limit == 0:
            return {key: 0 for key in keys}
        base = [limit * v // total for v in counts]
        remainders: Sequence[float] = [limit * v % total for v in counts]
    else:
        array = np.array([_number(v, f"weights[{key!r}]", False) for key, v in zip(keys, values)])
        if array.sum() == 0 or limit == 0:
            return {key: 0 for key in keys}
        raw = limit * array / array.sum()
        floor = np.floor(raw)
        base = [int(v) for v in floor]
        remainders = (raw - floor).tolist()
    order = sorted(range(len(keys)), key=lambda index: -remainders[index])
    for index in order[: limit - sum(base)]:
        base[index] += 1
    return dict(zip(keys, base))


def scale_to_capacity(targets: Mapping[str, int], capacity: int | None) -> dict[str, int]:
    """Targets scaled down by largest remainder when their total exceeds capacity; a total
    within capacity (or no capacity) is returned unchanged, never inflated."""
    result = _quantities(targets, "targets")
    limit = _capacity(capacity)
    if limit is None or sum(result.values()) <= limit:
        return result
    return proportional_allocation(result, limit)


def fill_gaps(
    targets: Mapping[str, int], floors: Mapping[str, int] | None, capacity: int | None
) -> dict[str, int]:
    """Top carried stock up toward targets within capacity.

    Each SKU keeps its carried stock (``floors``) and is offered ``max(target - floor, 0)``
    more units. When the gaps exceed the free space ``capacity - sum(floors)``, the free
    space is split in proportion to the gaps by largest remainder.
    """
    wanted = _quantities(targets, "targets")
    skus = list(wanted)
    start = _floors(floors, skus)
    gaps = {sku: max(wanted[sku] - start[sku], 0) for sku in skus}
    limit = _capacity(capacity)
    if limit is not None:
        free = limit - sum(start.values())
        if free < 0:
            raise ValueError(f"floors total {sum(start.values())} exceeds capacity {limit}")
        if sum(gaps.values()) > free:
            gaps = proportional_allocation(gaps, free)
    return {sku: start[sku] + gaps[sku] for sku in skus}


# Simulation -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Simulation:
    """A simulated run, one row per week and one column per SKU in every array.

    ``opening`` is stock carried in, ``ordered`` the units added before sales,
    ``start = opening + ordered``, ``covered = min(sales, start)``,
    ``lost = sales - covered``, ``closing = start - covered`` (carried to the next week);
    ``holding_cost = closing * price * holding_rate`` and
    ``shortage_cost = lost * price * shortage_rate``.
    """

    skus: tuple[str, ...]
    opening: np.ndarray
    ordered: np.ndarray
    start: np.ndarray
    sales: np.ndarray
    covered: np.ndarray
    lost: np.ndarray
    closing: np.ndarray
    holding_cost: np.ndarray
    shortage_cost: np.ndarray

    @property
    def cost(self) -> np.ndarray:
        return self.holding_cost + self.shortage_cost

    def records(self) -> dict[str, np.ndarray]:
        """Long-format columns, week by week: ``week`` (0-based index), ``sku``, the
        record fields and ``cost``."""
        weeks, count = self.sales.shape
        columns = {
            "week": np.repeat(np.arange(weeks), count),
            "sku": np.tile(np.array(self.skus, dtype=object), weeks),
        }
        for name in _RECORD_FIELDS:
            columns[name] = getattr(self, name).ravel()
        columns["cost"] = self.cost.ravel()
        return columns


def fixed_targets(targets: Mapping[str, int]) -> Policy:
    """A policy that orders up to the same targets every week (stock above a target is
    kept, never discarded)."""
    levels = _quantities(targets, "targets")

    def policy(week: int, carried: dict[str, int]) -> dict[str, int]:
        _require_keys(carried, list(levels), "carried stock")
        return {sku: max(level, carried[sku]) for sku, level in levels.items()}

    return policy


def simulate(
    skus: Sequence[str],
    sales: object,
    prices: object,
    policy: Policy,
    capacity: int | None,
    holding_rate: object,
    shortage_rate: object,
) -> Simulation:
    """Run a policy week by week over a (weeks x SKUs) matrix of integer sales.

    Columns of ``sales`` follow ``skus``. ``prices`` is one price per SKU or a
    (weeks x SKUs) matrix of each week's prices. The first week starts empty. Each week
    ``policy(week, carried)`` receives the 0-based week index and the stock carried in
    (a dict by SKU) and returns start-of-week stock, as a mapping by SKU or a sequence in
    ``skus`` order. Stock can only be added (start >= carried) and, unless ``capacity``
    is None, its total may not exceed ``capacity``. Sales beyond stock are lost; holding
    is charged on closing stock.
    """
    names = tuple(skus)
    if len(set(names)) != len(names) or not all(isinstance(sku, str) for sku in names):
        raise ValueError("skus must be unique SKU strings")
    units = _units(sales, "sales")
    if units.ndim != 2 or units.shape[1] != len(names):
        raise ValueError(f"sales must be a (weeks x {len(names)}) matrix, got shape {units.shape}")
    weeks = units.shape[0]
    price = np.asarray(prices, dtype=np.float64)
    if price.shape == (len(names),):
        price = np.broadcast_to(price, units.shape)
    if price.shape != units.shape:
        raise ValueError(f"prices must have shape ({len(names)},) or {units.shape}, got {price.shape}")
    if not (np.isfinite(price).all() and (price > 0).all()):
        raise ValueError("prices must be positive and finite")
    limit = _capacity(capacity)
    holding = float(_rate(holding_rate, "holding_rate"))
    shortage = float(_rate(shortage_rate, "shortage_rate"))

    shape = units.shape
    opening, start, covered = (np.zeros(shape, np.int64) for _ in range(3))
    carried = np.zeros(len(names), np.int64)
    for week in range(weeks):
        chosen = policy(week, dict(zip(names, carried.tolist())))
        if isinstance(chosen, Mapping):
            _require_keys(chosen, names, f"stock for week {week}")
            chosen = [chosen[sku] for sku in names]
        stock = _units(chosen, f"stock for week {week}")
        if stock.shape != (len(names),):
            raise ValueError(f"stock for week {week} must have one value per SKU")
        if (stock < carried).any():
            below = [sku for sku, low in zip(names, stock < carried) if low]
            raise ValueError(f"week {week}: stock below carried stock for {below}")
        if limit is not None and int(stock.sum()) > limit:
            raise ValueError(f"week {week}: stock {int(stock.sum())} exceeds capacity {limit}")
        opening[week], start[week] = carried, stock
        covered[week] = np.minimum(units[week], stock)
        carried = stock - covered[week]

    ordered = start - opening
    lost = units - covered
    closing = start - covered
    balanced = (
        (ordered >= 0).all()
        and (lost >= 0).all()
        and (closing >= 0).all()
        and np.array_equal(opening[1:], closing[:-1])
        and not opening[:1].any()
        and (limit is None or (start.sum(axis=1) <= limit).all())
    )
    if not balanced:
        raise AssertionError("simulated stock does not balance")
    record = {
        "opening": opening, "ordered": ordered, "start": start, "sales": units,
        "covered": covered, "lost": lost, "closing": closing,
        "holding_cost": closing * price * holding,
        "shortage_cost": lost * price * shortage,
    }
    for array in record.values():
        array.setflags(write=False)
    return Simulation(skus=names, **record)
