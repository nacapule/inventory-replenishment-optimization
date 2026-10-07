# Inventory Replenishment Under a Capacity Limit

This project compares weekly inventory-allocation policies on one year of UCI Online Retail
II data. It cleans the transactions, selects 20 recurring products from the training period,
compares three demand forecasts, and allocates a 7,060-unit weekly capacity with an empirical
newsvendor model.

## Results

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

Across the 11 sensitivities, the marginal optimizer's modeled cost was clearly lower than the scaled critical-fractile rule's in 2, clearly higher in 4 and not clearly different in 5; against proportional allocation, clearly lower in 1, clearly higher in 0 and not clearly different in 10. Full tables: [exports/insight_report.md](exports/insight_report.md).

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

## Model

For each SKU, the model minimizes expected weekly overage and shortage cost:

    min Σ hᵢ E[(qᵢ-Dᵢ)⁺] + pᵢ E[(Dᵢ-qᵢ)⁺]

subject to Σ qᵢ ≤ C and integer order quantities.

Each empirical cost curve is discrete convex. The algorithm assigns each additional unit
to the SKU with the largest marginal cost reduction. A unit test compares the result with
brute-force enumeration on a small case.

## Run

~~~bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make data
make test
make analyze
~~~

The make data command downloads the 43.5 MB workbook from UCI. The raw workbook and
generated SQLite database are ignored by Git.

## Files

- exports/insight_report.md - results, policy comparison, and model inputs
- exports/decision_summary.svg - chart of costs, forecasts, and allocation changes
- exports/policy_comparison.csv - results for the four allocation policies
- exports/sku_decisions.csv - product-level demand statistics and order quantities
- exports/forecast_metrics.csv - 12-week forecast backtest
- exports/qa_summary.md - row counts and train/test split
- exports/replenishment.db - generated SQLite database
- sql/analysis_queries.sql - example queries for the generated database

## Inputs and assumptions

- The analysis uses the Year 2010-2011 sheet and United Kingdom transactions.
- Products are selected using training-period activity and revenue only.
- Selling price is in the dataset; procurement cost, margin, lead time, case packs, and
  service targets are not.
- Holding cost is set to 5% of selling price per leftover unit-week.
- Shortage cost is set to 30% of selling price per unmet unit.
- Returns and cancellations are removed before weekly demand is calculated and are counted
  in the QA summary.

The 13.5% cost reduction depends on the two cost rates above. Both are command-line
arguments, so they can be changed for sensitivity testing.

## Data

Daqing Chen (2012), *Online Retail II*, UCI Machine Learning Repository.
[DOI 10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D). CC BY 4.0.

## See also

[retail-sales-dashboard](https://github.com/nacapule/retail-sales-dashboard) builds
the analytics and reporting layer on the same retailer's data — a DuckDB star schema
and a Power BI report whose fulfillment page uses this project's published results.
