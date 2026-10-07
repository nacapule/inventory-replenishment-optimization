# Inventory Replenishment Under a Capacity Limit

How should a retailer split a fixed amount of stock space across its top products when it replans every week? This project compares a cost-minimizing allocator, the **marginal optimizer**, with two simple rules on an online retailer's invoice lines from December 2009 to December 2011. **Proportional** allocation shares the space by each product's recent mean weekly sales; the **scaled critical-fractile** rule takes each product's cost-balancing stock level (its newsvendor quantity) and scales the levels down to fit.

Over a year of weekly decisions, the scaled critical-fractile rule had the lowest modeled cost within the limit. The optimizer cost clearly more than it and showed no clear difference from proportional allocation; it cost clearly less than the scaled rule only with the highest shortage penalty tested or a 13-week history. The advantage this project first published came from the data, not the method: orders reversed by an equal credit soon after they were placed had been counted as sales.

**Sales** are United Kingdom invoiced merchandise units after removing orders that the same known customer reversed with an equal credit within 24 hours (a **prompt reversal**); they stand in for the demand that stock could have met. **Modeled cost** is the holding and shortage charge described under The decision being modeled. **Fill rate** is the share of recorded sales units that simulated stock covered; it is not a service level, because sales the retailer could not make were never recorded. A cost difference is **clear** when its 95% bootstrap interval excludes zero.

## What the evidence shows

Generated from `exports/summary.json` by `make readme`.

<!-- results:start -->
Over the 52 evaluation weeks, 6 December 2010 to 4 December 2011, the marginal optimizer's modeled cost was 4.0% higher than the scaled critical-fractile rule's (95% interval 0.6% to 8.3% higher; it cost less in 20 of the 52 weeks and more in 32). Against proportional allocation, there was no clear difference: 1.3% lower in total (95% interval from 4.9% lower to 3.3% higher; it cost less in 27 of the 52 weeks and more in 25). The lowest modeled cost within the limit was the scaled critical-fractile rule's (£77,909); the unconstrained newsvendor, which ignores the limit, came to £76,403.

| Policy | Modeled cost | Fill rate | Mean leftover units |
| --- | ---: | ---: | ---: |
| Proportional to recent mean | £82,095 | 76.9% | 2,480 |
| Scaled critical-fractile | £77,909 | 77.8% | 2,434 |
| Marginal optimizer | £81,045 | 77.4% | 2,456 |
| Marginal optimizer, equal prices | £79,513 | 77.9% | 2,431 |
| Unconstrained newsvendor (reference, ignores the limit) | £76,403 | 88.4% | 5,132 |

![Cumulative weekly difference in modeled cost between the marginal optimizer and each baseline](exports/cost_difference.svg)

The figure adds up, week by week, the marginal optimizer's modeled cost minus each baseline's; below zero, the optimizer had cost less so far.

Across the 11 sensitivities, the marginal optimizer's modeled cost was clearly lower than the scaled critical-fractile rule's in 2, clearly higher in 4 and not clearly different in 5; against proportional allocation, clearly lower in 1, not clearly different in 10 and never clearly higher. The [results report](exports/insight_report.md) has the quarter, product and sensitivity tables.

**From the first published design, one correction at a time.** Rerun as originally designed, the marginal optimizer's modeled cost was 13.5% lower than proportional allocation's. With all 6 corrections applied, it was 3.7% higher than proportional allocation's. The steps "Prices from the training weeks only" and "Capacity from the smallest optimal quantities" left the products, the capacity and every cost as in the row before.

| Step | Training / holdout weeks | Capacity | Marginal optimizer | Scaled critical-fractile | Proportional | Optimizer vs proportional |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Published design | 42 / 12 | 7,060 | £24,209 | £23,352 | £27,972 | 13.5% lower |
| Remove sales reversed within 24 hours | 42 / 12 | 7,032 | £24,113 | £23,385 | £23,822 | 1.2% higher |
| Exclude charge, accounting, voucher and manual codes | 42 / 12 | 7,249 | £23,780 | £23,207 | £23,071 | 3.1% higher |
| Merge stock codes that differ only in case | 42 / 12 | 7,250 | £23,776 | £23,233 | £23,070 | 3.1% higher |
| Complete weeks only | 40 / 12 | 7,689 | £24,188 | £23,881 | £23,330 | 3.7% higher |
| Prices from the training weeks only | 40 / 12 | 7,689 | £24,188 | £23,881 | £23,330 | 3.7% higher |
| Capacity from the smallest optimal quantities | 40 / 12 | 7,689 | £24,188 | £23,881 | £23,330 | 3.7% higher |

Each row scores targets set once for a single holdout period, as the first published design did. The scaled critical-fractile column was not part of that design; it is computed at every step for reference.
<!-- results:end -->

- **The first published advantage came from the data.** That design counted prompt reversals as sales. Removing them (second row of the last table) ended the optimizer's advantage over proportional allocation by lowering proportional allocation's cost; the optimizer's barely changed.
- **A simple rule had the lowest cost over the year.** The marginal optimizer, optimal for the history it is fitted to each week, cost clearly more than the scaled rule, most of the gap arising in the [last quarter](exports/insight_report.md#by-quarter), when every policy's cost was higher. The ranking was the same with the data cleaned as in the first published design.
- **The ranking depends on the settings.** At the highest critical ratio tested, the optimizer cost clearly less than both baselines; with only 13 weeks of history, both optimizers cost less than the scaled rule, clearly so for the marginal optimizer. Under the primary settings, the equal-price optimizer cost less than the marginal optimizer (no interval was computed for that pair) but more than the scaled rule. See the [sensitivities](exports/insight_report.md#sensitivities).

## The decision being modeled

Each Monday, every policy sets each product's start-of-week stock from the sales and prices recorded before that week. Replenishment arrives at once (zero lead time), sales beyond the units on hand are lost, and leftover units carry into the next week. The first evaluation week starts empty.

**Capacity** is a hypothetical limit on total start-of-week stock, counted in units because the data has no product sizes. It is the selected products' mean weekly sales over the selection year (weeks with invoices only), rounded to a whole unit and the same for every policy.

Modeled cost charges 5% of a product's price for each unit left over at the end of a week and 30% for each unit of sales not covered: for a £2.00 item, 10p and 60p. Both rates are assumptions. Only their ratio changes which stock levels are best, the **critical ratio** 30 / (5 + 30) = 6/7; their level scales every policy's cost alike.

The marginal optimizer solves:

    minimize    Σᵢ priceᵢ · ( h · E[(xᵢ − Dᵢ)⁺] + p · E[(Dᵢ − xᵢ)⁺] )
    subject to  Σᵢ xᵢ ≤ C,   xᵢ ≥ carriedᵢ,   xᵢ whole units

Here xᵢ is product i's start-of-week stock, carriedᵢ its carried-in stock, priceᵢ its price and Dᵢ one week's sales; C is the capacity, h and p the two rates, (z)⁺ the larger of z and zero, and E the average over the weeks of the history window. Each product's expected cost is convex in its stock, so giving units one at a time to the product whose next unit lowers cost most reaches the minimum, hence "marginal". "Optimal" means optimal for the fitted history, not for the weeks that follow.

## Policies

A product's **newsvendor quantity** (its **critical fractile**) is the smallest stock level at which the share of history weeks with sales at or below it reaches the critical ratio.

| Policy | Rule |
| --- | --- |
| Proportional to recent mean | Shares the limit in proportion to each product's mean weekly sales over the history window. |
| Scaled critical-fractile | Takes each product's newsvendor quantity and scales them all down to the limit when their total exceeds it. |
| Marginal optimizer | Solves the problem above, starting from carried stock. |
| Marginal optimizer, equal prices | The same allocation with every price set to one, scored at real prices: a diagnostic of what price weighting contributes. |
| Unconstrained newsvendor | Each product's newsvendor quantity with no limit: a reference only. |

The two rules set a target per product and order the gap above carried stock; when the gaps exceed the free space, it is shared in proportion to the gaps. No policy discards stock.

## Data

The study combines both workbook sheets, keeps United Kingdom lines in complete Monday-to-Sunday weeks, and matches stock codes in upper case. A [code registry](data/code_registry.csv) excludes charges, accounting codes, test codes, vouchers and manual entries. Credits other than prompt reversals stay in a ledger and are never netted against sales.

An example of a prompt reversal: invoice 541431 records a known customer buying 74,215 units of code 23166 at 10:01 on 18 January 2011, and credit C541433 reverses it in full sixteen minutes later. The first published design ignored credit lines, so this order stayed in its sales. A pair counts as sales until its credit is recorded; a decision uses only credits recorded before it.

The last table in the results block starts from that first design (the 2010–2011 sheet alone, a single 12-week holdout, targets set once) and adds one correction per row. Removing prompt reversals lowers proportional allocation's cost and barely moves the optimizer's. Proportional allocation follows each product's mean weekly sales, which one huge week raises in proportion to its size; the newsvendor quantity and the optimizer use the share of weeks below each stock level, which one week can change by only one week's worth. The [data report](exports/data_quality.md) reconciles every source row to its classification.

## How the evaluation works

The first 52 complete weeks are the **selection year**: they pick the 20 highest-revenue products among those sold in at least 26 of those weeks and set the capacity. The next 52 are the **evaluation year**, replanned each Monday and scored. Each decision uses a **history window**, by default the trailing 52 complete weeks; weeks with no invoice anywhere are left out of it and scored as weeks without sales. A product's price is its median over the 52 weeks before the decision. The sales scored in a week include only the credits recorded by its end.

Differences in total modeled cost are judged with a paired moving-block bootstrap: both policies' weekly costs are resampled together in 4-week blocks, 10,000 times. Blocks of 2 and 8 weeks serve as checks; for the optimizer against the scaled rule, the 8-week interval includes zero. The primary configuration and eleven sensitivities, each changing one factor, were declared before any result was computed, except one whose label says it was added after an exploratory result favored it; all are in [`configs/published.toml`](configs/published.toml).

## What real use would need

Real use would need on-hand stock, supplier lead times, procurement costs and margins, case packs or minimum orders, and capacity in volume or shelf space. With a lead time, each order must cover sales until the next delivery and stock on order matters, so decisions would depend on supplier behavior this data does not record.

## Reproduce or change a scenario

Use Python 3.14 with the exact versions in `requirements.txt`:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make data      # download the workbook and check its size and SHA-256
make test      # unit tests; those that need the workbook skip without it
make analyze   # rebuild exports/, replaced only once the new bundle is complete
make readme    # refresh the results block from exports/summary.json
make verify    # rebuild in a temporary folder and compare every artifact byte for byte
~~~

For another scenario, copy and edit `configs/published.toml`, which holds every setting and is checked before the workbook is read, then write to another folder:

~~~bash
python src/replenishment.py analyze --config <copy> --output <folder>
~~~

## Outputs

`exports/` holds the results report `insight_report.md`, the data report `data_quality.md` (which also defines every CSV column), the figure, and:

- `policy_comparison.csv`, `sku_decisions.csv` and `forecast_metrics.csv`, with names, columns and row grain kept for the companion dashboard; `sku_decisions.csv` holds next-week targets for every policy except the equal-price diagnostic;
- `weekly_results.csv`, `weekly_sales.csv`, `sensitivity.csv`, `published_bridge.csv`, `reconciliation.csv` and `reversal_pairs.csv`;
- `summary.json`, every number in the results block and the results report, and `run_manifest.json`, the configuration, input and source-file hashes, package versions and artifact hashes.

`src/` holds the command line (`replenishment.py`) and four modules: `data.py` reads and classifies lines, `model.py` allocates and simulates stock, `experiment.py` runs the study and `report.py` writes the reports and exports.

## Source and related work

Daqing Chen (2012), *Online Retail II*, UCI Machine Learning Repository. [DOI 10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D), CC BY 4.0. Code: [MIT License](LICENSE).

The companion [retail-sales-dashboard](https://github.com/nacapule/retail-sales-dashboard) reports on the same retailer's data: a DuckDB star schema and a Power BI report whose fulfillment page uses this project's policy, product and forecast tables.
