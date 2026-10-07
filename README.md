# Inventory Replenishment Under a Capacity Limit

How should a retailer split fixed start-of-week stock space across its best-selling products, replanning weekly for a year? This study compares a cost-minimizing allocator with simple rules. A rule that scales product stock targets to fit the limit led under the primary settings. The optimizer's earlier advantage came from counting a reversed sale; it led over the year under some alternative settings.

**Sales** means United Kingdom invoiced merchandise units after removing orders the same customer reversed with an equal credit within 24 hours. These sales stand in for the demand that stock could have met. **Fill rate** is the share of recorded sales units simulated stock covered. It is not a service level: sales the retailer could not make were never recorded.

## What the evidence shows

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

Across the 11 sensitivities, the marginal optimizer's modeled cost was clearly lower than the scaled critical-fractile rule's in 2, clearly higher in 4 and not clearly different in 5; against proportional allocation, clearly lower in 1, clearly higher in 0 and not clearly different in 10. See the [results report](exports/insight_report.md) for quarter, product and sensitivity tables.

**From the published figure to this one.** Rerun as originally designed, the marginal optimizer's modeled cost was 13.5% lower than proportional allocation's. With all 6 corrections applied, it was 3.7% higher than proportional allocation's and 1.3% higher than the scaled critical-fractile rule's.

| Step | Training / holdout weeks | Capacity | Marginal optimizer | Scaled critical-fractile | Proportional | Optimizer vs proportional |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Published design | 42 / 12 | 7,060 | £24,209 | £23,352 | £27,972 | 13.5% lower |
| Remove sales reversed within 24 hours | 42 / 12 | 7,032 | £24,113 | £23,385 | £23,822 | 1.2% higher |
| Exclude charge, accounting, voucher and manual codes | 42 / 12 | 7,249 | £23,780 | £23,207 | £23,071 | 3.1% higher |
| Merge stock codes that differ only in case | 42 / 12 | 7,250 | £23,776 | £23,233 | £23,070 | 3.1% higher |
| Complete weeks only | 40 / 12 | 7,689 | £24,188 | £23,881 | £23,330 | 3.7% higher |
| Prices from the training weeks only | 40 / 12 | 7,689 | £24,188 | £23,881 | £23,330 | 3.7% higher |
| Capacity from the smallest optimal quantities | 40 / 12 | 7,689 | £24,188 | £23,881 | £23,330 | 3.7% higher |
<!-- results:end -->

- **The original advantage came from the data.** Removing prompt reversals erased the optimizer's advantage over the proportional rule in the original design. See the [bridge table](exports/insight_report.md#from-the-published-design) and the Data section below.
- **A simple rule led over the year.** The scaled rule had the lowest modeled cost within the limit. The optimizer cost clearly more by the predeclared rule: its interval calculated with 4-week blocks excludes zero. The 2-week check agrees, while the 8-week check includes zero. Its difference from the proportional rule was not clear. Most of the optimizer's cost gap against the scaled rule arose in the [last evaluation quarter](exports/insight_report.md#by-quarter), when all policies cost more than in other quarters. The ranking held with the original cleaning too.
- **The ranking depended on the settings.** At the highest tested uncovered-sales penalty, the optimizer cost clearly less than both baselines; at the next-highest, it led within the limit but its intervals included zero. With 13 weeks of history, both optimizers cost less than the scaled rule, clearly so for the price-weighted one; the equal-price version led. Under primary settings, equal prices cost less than price weighting, but more than the scaled rule. No interval was computed between the optimizers. See [sensitivities](exports/insight_report.md#sensitivities).

## The decision being modeled

Each Monday, policies set start-of-week stock from sales and prices recorded before that week. Replenishment arrives immediately, with zero lead time. Stock covers sales up to the units on hand; the rest are lost in the simulation. Leftovers carry forward and incur holding cost. Evaluation starts empty.

Capacity limits total start-of-week stock in units, because product sizes are absent. This hypothetical limit is the selected products' mean weekly sales over selection weeks with invoices, rounded to a whole unit and fixed for every policy.

Holding a leftover unit for a week costs 5% of price; an uncovered sales unit costs 30%. For a £2.00 item, the charges are 10p and 60p. Both rates are assumptions. Only their **critical ratio**, 30 / (5 + 30) = 6/7, changes preferred stock levels for the history; scaling both rates together scales every policy's cost alike.

The optimizer solves:

    minimize    Σᵢ priceᵢ · ( h · E[(xᵢ − Dᵢ)⁺] + p · E[(Dᵢ − xᵢ)⁺] )
    subject to  Σᵢ xᵢ ≤ C,   xᵢ ≥ carriedᵢ,   xᵢ whole units

For product i, xᵢ is start-of-week stock, carriedᵢ is stock carried in, priceᵢ is its price, and Dᵢ is one week's sales. C is capacity; h and p are the holding and shortage rates. The positive-part symbol ⁺ means the larger of the bracketed value and zero. E averages equally over history weeks. Each product's expected cost is convex: successive units offer diminishing reductions. Assigning units where they reduce cost most, until none helps or capacity is full, minimizes cost for that history.

## Policies

A **newsvendor quantity**, or **critical fractile**, is the smallest stock level at which the history's share of weeks with sales at or below it reaches the critical ratio.

| Policy | Rule |
| --- | --- |
| Proportional to recent mean | Shares the limit in proportion to each product's mean weekly sales. |
| Scaled critical-fractile | Scales newsvendor quantities down to the limit when their total exceeds it. |
| Marginal optimizer | Solves the problem above, starting from carried stock. |
| Marginal optimizer, equal prices | Allocates with every price set to one, then scores at real prices to show what price weighting contributes. |
| Unconstrained newsvendor | Uses each product's newsvendor quantity without a shared limit; a reference only. |

The target rules top up carried stock. If targets do not fit beside it, free space is shared in proportion to each product's shortfall. Stock is never thrown away.

## Data

The study combines both workbook sheets, covering December 2009 to December 2011, and uses United Kingdom lines and complete Monday-to-Sunday weeks. The [code registry](data/code_registry.csv) excludes charges, accounting codes, test codes, vouchers and manual entries. Codes are matched in upper case. Credits outside prompt reversals stay in a ledger, never netted against sales.

For example, invoice 541431 records customer 12346 buying 74,215 units of code 23166 at £1.04 at 10:01 on 18 January 2011. Credit C541433 reverses it exactly at 10:17, sixteen minutes later. The original design dropped credits, keeping this order in sales. A prompt reversal requires the same known customer, code, price and quantity. The pair counts as sales until its credit is recorded; a decision uses only credits recorded before it.

The table **“From the published figure to this one”** starts with the first published design: one sheet, a single 12-week holdout and fixed targets. The first row reproduces its result; each later row adds one correction. Removing reversed sales in the second row erases the optimizer's advantage because proportional allocation's cost falls most. A mean is pulled up by a very large week; a quantile at the critical ratio barely moves. The [data report](exports/data_quality.md) gives the full classification.

## How the evaluation works

The first 52 complete weeks select the 20 highest-revenue products sold in at least 26 selection weeks and set capacity. The next 52 evaluate weekly decisions. Primary history is the trailing 52 complete weeks; weeks with no invoice anywhere are omitted from history and scored with no sales.

Prices are each product's median unit price over the preceding 52 weeks, used to allocate and score the week. Evaluation sales reflect credits known at week-end; later credits never rewind stock.

Total modeled costs are compared with a paired moving-block bootstrap: both policies' weekly costs are resampled together in consecutive 4-week blocks, 10,000 times. A difference is clear only when its 95% interval excludes zero. The primary configuration and eleven one-at-a-time sensitivities were predeclared, except the row labeled as added after an exploratory result favored it.

## What real use would need

Real use needs on-hand stock, supplier lead times, procurement cost and margins, case packs or minimum orders, and capacity in volume or shelf space. With lead time, orders cover sales until the next delivery and stock on order matters, so decisions depend on supplier behavior absent from this data.

## Reproduce or change a scenario

Use Python 3.14 and `requirements.txt`'s exact package versions:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make data
make test
make analyze
make readme
make verify
~~~

`make data` downloads the UCI archive, unzips the workbook into `data/raw/`, and checks its size and SHA-256 against `configs/published.toml`. `make test` runs unit tests; workbook-dependent tests are skipped without it. `make analyze` replaces `exports/` only when the new bundle is complete. `make readme` updates the results block from `exports/summary.json`. `make verify` rebuilds in a temporary folder, compares every artifact byte for byte, and checks the manifest's input and source hashes.

For another scenario, copy and edit `configs/published.toml`; use another output folder to preserve published exports:

~~~bash
python src/replenishment.py analyze --config <copy> --output <folder>
~~~

Configuration is checked before reading the workbook. There are no separate scenario-setting flags.

## Outputs

In `exports/`:

- `insight_report.md`: results and method.
- `data_quality.md`: data classification and every exported CSV column's meaning.
- `cost_difference.svg`: cumulative modeled cost differences.
- `policy_comparison.csv`, `sku_decisions.csv`, `forecast_metrics.csv`: policy, product and forecast tables with names, columns and row grain kept for the companion dashboard. `sku_decisions.csv` targets the week after evaluation.
- `weekly_results.csv`: every policy, product and evaluation week.
- `sensitivity.csv`: scenario comparisons.
- `published_bridge.csv`: the bridge from the first published design.
- `reconciliation.csv`: source-row roles, summing to the workbook.
- `reversal_pairs.csv`: matched prompt reversals.
- `weekly_sales.csv`: cohort sales by week.
- `summary.json`: every number quoted by the reports and README block.
- `run_manifest.json`: configuration, input and source-file hashes, package versions and artifact hashes.

`configs/published.toml` holds the study settings; `data/code_registry.csv` classifies codes; `templates/` holds report wording. In `src/`, `data.py` reads and classifies lines, `model.py` allocates and simulates stock, `experiment.py` runs the study, `report.py` produces reports and exports, and `replenishment.py` provides the command line.

## Source and related work

Daqing Chen (2012), *Online Retail II*, UCI Machine Learning Repository. [DOI 10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D), CC BY 4.0. Code: [MIT License](LICENSE).

The companion [retail-sales-dashboard](https://github.com/nacapule/retail-sales-dashboard) reports on the same retailer: a DuckDB star schema and Power BI report whose fulfillment page uses this project's policy, product and forecast tables.
