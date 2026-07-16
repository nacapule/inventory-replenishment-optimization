# Inventory Under Constraint

## Decision summary

Using the same 7,060-unit weekly capacity, the marginal optimizer reduced holdout scenario cost by **13.5%** relative to proportional allocation. Its demand fill rate was **65.0%**, compared with **56.7%** for the baseline.

Across the forecast baselines, **Exponential smoothing** performed best with **50.8% WAPE** on the final 12 weeks.

## What was optimized

For each SKU, weekly demand is represented by its empirical training distribution. The decision balances holding cost for leftover units against shortage cost for unmet demand:

`min Σ hᵢ E[(qᵢ-Dᵢ)⁺] + pᵢ E[(Dᵢ-qᵢ)⁺]`, subject to `Σ qᵢ ≤ capacity`.

Because each SKU's empirical expected-cost curve is discrete convex, allocating each additional unit to the SKU with the greatest marginal cost reduction gives the global optimum for the shared unit-capacity constraint.

## Policy comparison

| Policy | Units | Fill rate | Stockout SKU-weeks | Holding cost | Shortage cost | Scenario cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Newsvendor unconstrained | 8,306 | 70.5% | 19.6% | £9,529 | £13,413 | £22,942 |
| Optimized under capacity | 7,060 | 65.0% | 25.0% | £7,409 | £16,800 | £24,209 |
| Proportional mean under capacity | 7,060 | 56.7% | 32.5% | £5,493 | £22,479 | £27,972 |
| Historical mean unconstrained | 6,716 | 55.0% | 35.0% | £4,959 | £23,609 | £28,569 |

## Largest allocation changes

| SKU | Description | Proportional | Optimized | Shift |
| --- | --- | ---: | ---: | ---: |
| 23166 | MEDIUM CERAMIC TOP STORAGE JAR | 1,899 | 82 | -1,817 |
| 85123A | WHITE HANGING HEART T-LIGHT HOLDER | 703 | 986 | +283 |
| 85099B | JUMBO BAG RED RETROSPOT | 763 | 1,026 | +263 |
| 23298 | SPOTTY BUNTING | 138 | 373 | +235 |
| 47566 | PARTY BUNTING | 379 | 594 | +215 |
| 85099F | JUMBO BAG STRAWBERRY | 314 | 491 | +177 |
| 84879 | ASSORTED COLOUR BIRD ORNAMENT | 588 | 740 | +152 |
| 22386 | JUMBO BAG PINK POLKADOT | 334 | 478 | +144 |

## Why the largest shift matters

SKU `23166` contains a 74,215-unit training week, versus a typical positive week of 81.5 units (911x larger). That one event pulls its training mean to 1,806.7 units and causes the proportional-mean baseline to reserve 1,899 units every week. The empirical optimizer assigns 82 instead because a rare bulk order does not justify permanent capacity under the stated cost assumptions.

Operationally, the spike should be investigated rather than deleted automatically. If it was a known wholesale order, it belongs in a separate event/order channel; if it was an error, it belongs in source-data QA. Either way, a routine replenishment forecast should not treat it as ordinary weekly demand.

## Evidence boundaries

- Source: UCI Online Retail II, sheet `Year 2010-2011`, filtered to `United Kingdom`.
- Train / holdout split: 42 / 12 weekly periods, in chronological order.
- Holding cost is a scenario assumption of 5.0% of unit price per leftover unit-week.
- Shortage cost is a scenario assumption of 30.0% of unit price per unmet unit.
- Unit price is observed; procurement cost, lead time, margin, shelf life, and service contracts are not.
- A fixed weekly order-up-to quantity is evaluated against holdout demand. This is a decision lab, not a production inventory recommendation.
- Product selection uses training-period activity and revenue only; holdout outcomes do not select SKUs.

## Next operational questions

1. How does the allocation change under supplier-specific lead times and case-pack constraints?
2. Which SKUs retain priority across plausible holding/shortage cost scenarios?
3. Does a rolling demand distribution outperform a fixed training distribution after demand shifts?
4. What service-level commitments justify reserving capacity for low-volume, high-value SKUs?
