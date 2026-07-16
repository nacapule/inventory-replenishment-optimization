# Inventory Replenishment Under a Capacity Limit

## Results

Using the same 7,060-unit weekly capacity, the marginal optimizer reduced holdout modeled cost by **13.5%** relative to proportional allocation. Its demand fill rate was **65.0%**, compared with **56.7%** for the baseline.

Across the forecast baselines, **Exponential smoothing** performed best with **50.8% WAPE** on the final 12 weeks.

## Model

For each SKU, weekly demand is represented by its empirical training distribution. The decision balances holding cost for leftover units against shortage cost for unmet demand:

`min Σ hᵢ E[(qᵢ-Dᵢ)⁺] + pᵢ E[(Dᵢ-qᵢ)⁺]`, subject to `Σ qᵢ ≤ capacity`.

Because each SKU's empirical expected-cost curve is discrete convex, allocating each additional unit to the SKU with the greatest marginal cost reduction gives the global optimum for the shared unit-capacity constraint.

## Policy comparison

| Policy | Units | Fill rate | Stockout SKU-weeks | Holding cost | Shortage cost | Modeled cost |
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

## Outlier check

SKU `23166` contains a 74,215-unit training week, versus a typical positive week of 81.5 units (911x larger). That one event pulls its training mean to 1,806.7 units and causes the proportional-mean baseline to reserve 1,899 units every week. The empirical optimizer assigns 82 instead.

I would flag this product before using it in a recurring forecast. A confirmed wholesale order should be modeled separately; a source-data error should be corrected upstream.

## Inputs and assumptions

- Source: UCI Online Retail II, sheet `Year 2010-2011`, filtered to `United Kingdom`.
- Train / holdout split: 42 / 12 weekly periods, in chronological order.
- Holding cost: 5.0% of unit price per leftover unit-week.
- Shortage cost: 30.0% of unit price per unmet unit.
- Unit price is observed; procurement cost, lead time, margin, shelf life, and service contracts are not.
- Product selection uses training-period activity and revenue only; holdout outcomes do not select SKUs.

## Follow-up tests

1. Add supplier lead times and case-pack constraints.
2. Vary the holding and shortage rates.
3. Compare the fixed training distribution with a rolling window.
4. Add product-level service targets.
