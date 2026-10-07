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
from fractions import Fraction
from typing import Callable, Mapping, Sequence

import numpy as np

Policy = Callable[[int, dict[str, int]], "Mapping[str, int] | Sequence[int]"]

_RECORD_FIELDS = ("opening", "ordered", "start", "sales", "covered", "lost", "closing",
                  "holding_cost", "shortage_cost")


# Input checks ---------------------------------------------------------------------------


def _units(values: object, name: str) -> np.ndarray:
    """Non-negative whole units as int64: integers, or floats with integral values."""
    array = np.asarray(values)
    if array.dtype.kind not in "iuf":
        raise ValueError(f"{name} must hold numbers of units, got {array.dtype} values")
    if array.dtype.kind == "f":
        if not np.isfinite(array).all():
            raise ValueError(f"{name} contains NaN or infinite values")
        if (array != np.trunc(array)).any():
            raise ValueError(f"{name} contains fractional units")
    if array.size and array.min() < 0:
        raise ValueError(f"{name} contains negative units")
    return array.astype(np.int64)


def _count(value: object, name: str) -> int:
    array = _units(value, name)
    if array.ndim:
        raise ValueError(f"{name} must be a single number of units")
    return int(array)


def _capacity(value: object) -> int | None:
    return None if value is None else _count(value, "capacity")


def _samples(values: object, name: str) -> np.ndarray:
    array = _units(values, name)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty sequence of weekly units")
    return array


def _sorted_history(histories: Mapping, sku: str) -> list[int]:
    return np.sort(_samples(histories[sku], f"history for {sku!r}")).tolist()


def _rate(value: object, name: str) -> Fraction:
    """A finite non-negative rate, exactly. A float is read as the decimal it prints as
    (0.05 is 1/20), which is the value written in a configuration file."""
    if isinstance(value, numbers.Integral):
        value = int(value)  # a NumPy integer inside a Fraction would overflow
    try:
        rate = Fraction(repr(float(value)) if isinstance(value, float) else value)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        raise ValueError(f"{name} must be a finite number, got {value!r}") from None
    if rate < 0:
        raise ValueError(f"{name} must be non-negative, got {value!r}")
    return rate


def _amount(value: object, name: str, positive: bool) -> Fraction:
    """A finite price (positive) or weight (non-negative), at its exact value."""
    finite = isinstance(value, numbers.Real) and math.isfinite(value)
    if finite and (value > 0 if positive else value >= 0):
        if isinstance(value, numbers.Integral):
            return Fraction(int(value))  # a NumPy integer inside a Fraction would overflow
        return Fraction(value) if isinstance(value, numbers.Rational) else Fraction(float(value))
    kind = "positive" if positive else "non-negative"
    raise ValueError(f"{name} must be a finite {kind} number, got {value!r}")


def _sku_keys(mapping: object, name: str) -> list[str]:
    if not isinstance(mapping, Mapping) or not all(isinstance(key, str) for key in mapping):
        raise ValueError(f"{name} must be a mapping from SKU strings to values")
    return list(mapping)


def _require_keys(mapping: Mapping, skus: Sequence[str], name: str) -> None:
    if not isinstance(mapping, Mapping) or set(mapping) != set(skus):
        raise ValueError(f"{name} must have exactly the SKUs {sorted(skus)} as keys")


def _quantities(mapping: object, name: str) -> dict[str, int]:
    return {sku: _count(mapping[sku], f"{name}[{sku!r}]") for sku in _sku_keys(mapping, name)}


def _floors(floors: Mapping[str, int] | None, skus: Sequence[str]) -> dict[str, int]:
    if floors is None:
        return {sku: 0 for sku in skus}
    _require_keys(floors, skus, "floors")
    return {sku: _count(floors[sku], f"floors[{sku!r}]") for sku in skus}


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
    its unit price (``None`` weighs every SKU equally: the equal-price diagnostic).
    Holding and shortage cost per unit are ``price * holding_rate`` and
    ``price * shortage_rate``. Stock starts at ``floors`` (carried stock, default zero)
    and only the free space ``capacity - sum(floors)`` is allocated; ``capacity=None``
    removes the limit and returns the smallest unconstrained optimum.

    Units go to the most negative price-weighted marginal first; equal marginals go to the
    SKU that sorts first. A SKU stops receiving units once its next marginal is not
    negative. Both the comparison and the stop are exact (integer counts, the rates as
    fractions, prices at their exact value). Between consecutive sample values the
    marginal is flat, so such a run of units is taken in one step, with the same result
    as adding them one at a time.
    """
    skus = _sku_keys(histories, "histories")
    samples = {sku: _sorted_history(histories, sku) for sku in skus}
    if prices is None:
        price = {sku: Fraction(1) for sku in skus}
    else:
        _require_keys(prices, skus, "prices")
        price = {sku: _amount(prices[sku], f"prices[{sku!r}]", True) for sku in skus}
    allocation = _floors(floors, skus)
    limit = _capacity(capacity)
    free = None if limit is None else limit - sum(allocation.values())
    if free is not None and free < 0:
        raise ValueError(f"floors total {sum(allocation.values())} exceeds capacity {limit}")
    holding, shortage = _rate(holding_rate, "holding_rate"), _rate(shortage_rate, "shortage_rate")
    scale = math.lcm(holding.denominator, shortage.denominator)
    slope = int((holding + shortage) * scale)  # integers: marginal * scale * n / price
    offset = int(shortage * scale)  #           equals slope * #{D <= x} - offset * n
    # weight * excess is the price-weighted marginal times one positive constant shared
    # by every SKU, so the ordering, and ties between SKUs, are exact.
    common = math.lcm(*(price[sku].denominator * len(samples[sku]) for sku in skus))
    weight = {
        sku: price[sku].numerator * (common // (price[sku].denominator * len(samples[sku])))
        for sku in skus
    }

    def next_step(sku: str) -> tuple[int, str, int] | None:
        """The SKU's next marginal and how many units share it, or None if not negative."""
        values, level = samples[sku], allocation[sku]
        covered = bisect_right(values, level)
        excess = slope * covered - offset * len(values)
        if excess >= 0:
            return None
        # covered < n here; F, and with it the marginal, is flat up to the next sample.
        return weight[sku] * excess, sku, values[covered] - level

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
        values = _sorted_history(histories, sku)
        result[sku] = values[math.ceil((len(values) - 1) * ratio)]
    return result


def proportional_allocation(weights: Mapping[str, float], capacity: int) -> dict[str, int]:
    """Split ``capacity`` in proportion to ``weights`` by largest remainder.

    The quotas are computed exactly from the weights' values. The result sums to
    ``capacity`` unless every weight is zero; equal remainders go to the key that comes
    first in ``weights``.
    """
    keys = _sku_keys(weights, "weights")
    limit = _count(capacity, "capacity")
    exact = [_amount(weights[key], f"weights[{key!r}]", False) for key in keys]
    scale = math.lcm(*(value.denominator for value in exact))
    counts = [value.numerator * (scale // value.denominator) for value in exact]
    total = sum(counts)
    if total == 0 or limit == 0:
        return {key: 0 for key in keys}
    base = [limit * count // total for count in counts]
    remainders = [limit * count % total for count in counts]
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
    price = np.asarray(prices)
    if price.dtype.kind not in "iuf" or not (np.isfinite(price).all() and (price > 0).all()):
        raise ValueError("prices must be positive finite numbers")
    if price.shape == (len(names),):
        price = np.broadcast_to(price, units.shape)
    if price.shape != units.shape:
        raise ValueError(f"prices must have shape ({len(names)},) or {units.shape}, got {price.shape}")
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
            raise ValueError(f"week {week}: stock below the stock carried in")
        if limit is not None and int(stock.sum()) > limit:
            raise ValueError(f"week {week}: stock {int(stock.sum())} exceeds capacity {limit}")
        opening[week], start[week] = carried, stock
        covered[week] = np.minimum(units[week], stock)
        carried = stock - covered[week]

    ordered = start - opening
    lost = units - covered
    closing = start - covered
    if not ((ordered >= 0).all() and (lost >= 0).all() and (closing >= 0).all()
            and np.array_equal(opening[1:], closing[:-1]) and not opening[:1].any()
            and (limit is None or (start.sum(axis=1) <= limit).all())):
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
