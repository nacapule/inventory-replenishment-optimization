# Inventory Replenishment Under a Capacity Limit

This project compares weekly inventory-allocation policies on one year of UCI Online Retail
II data. It cleans the transactions, selects 20 recurring products from the training period,
compares three demand forecasts, and allocates a 7,060-unit weekly capacity with an empirical
newsvendor model.

![Decision summary](exports/decision_summary.svg)

## Results

On the final 12 weeks, the optimized allocation had a modeled cost of **£24,209**, compared
with **£27,972** for proportional mean allocation. Both policies used 7,060 units per week.
Fill rate increased from **56.7%** to **65.0%**.

The largest change was SKU 23166. Its training data contains one 74,215-unit week, while
its median positive week is about 82 units. That single order pushes the mean high enough
for the proportional baseline to assign 1,899 units every week. The optimizer assigns 82.
Before using this SKU in a recurring forecast, I would check whether the large order was a
wholesale event or a source-data error.

The full tables are in [exports/insight_report.md](exports/insight_report.md).

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
