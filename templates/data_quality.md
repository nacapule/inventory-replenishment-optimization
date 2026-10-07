# Data quality and reconciliation

## Source rows

The workbook has two sheets ($sheet_rows; $source_rows rows in all). The older sheet repeats the first $overlap_rows rows of the newer one; that copy is set aside after checking that it is identical, which leaves $combined_rows rows. Every source row receives exactly one role, so the table sums to the workbook.

$reconciliation_table

- **overlap**: the older sheet's copy of rows that the newer sheet also holds.
- **accounting_invoice**: invoices numbered with an A (bad-debt adjustments).
- **invalid**: a missing or malformed field, or a quantity that is not a whole, non-zero number.
- **prompt_reversal_sale / prompt_reversal_credit**: a sale and the equal credit that reversed it within $reversal_hours hours (same known customer, stock code, price and quantity, credit strictly later).
- **ledger_credit**: every other credit line. Credits are kept in a ledger and never netted against sales.
- **stock_adjustment**: negative quantities without a credit invoice, all at zero price.
- **zero_price**: positive lines with a price of zero.
- **non_merchandise / quarantined**: charges, accounting codes, test codes, vouchers and manual entries listed in `data/code_registry.csv`.
- **merchandise_sale**: everything else, the lines that count as sales.

## The cohort

The $cohort_size products with the highest revenue in the selection year ($selection_first to $selection_last) among those sold in at least $min_active_weeks of its weeks, counted as known when the evaluation year began. They and the capacity stay fixed for the whole study.

$selection_table

## From accepted lines to the study ($country)

$stage_table

Accepted lines are positive, priced, non-credit sale lines, as the project first counted them. Merchandise drops the registry codes and A invoices. Prompt reversals are then removed, then the partial weeks at both ends of the data. The study cohort is the $cohort_size products over the selection and evaluation years.

## Orders reversed within $reversal_hours hours

$prompt_pairs sale lines in the $country ($prompt_units units) were reversed by an equal credit within $reversal_hours hours; $all_prompt_pairs such pairs exist across all countries. Each pair counts as sales until its credit is recorded and is removed from then on, so a decision never uses a credit recorded after it. $cohort_prompt_pairs of the $country pairs ($cohort_prompt_units units) involve cohort products. The largest:

$largest_pairs_table

Every pair, with both rows' sheet and spreadsheet row, is in `reversal_pairs.csv`.

## Credit lines ($country)

$credit_table

A credit matches exactly when an earlier sale has the same known customer, stock code, price and quantity; each sale is used once, by the latest earlier match. Matches later than $reversal_hours hours stay in the ledger. Re-invoiced counts the later credits followed within $reversal_hours hours by an equal sale; that sale may repeat the credited one, so up to that many units may be counted twice in sales.

## Codes that are not merchandise ($country)

$registry_table

## Retained codes that are not digits plus a letter suffix ($country)

These codes stay in sales as merchandise.

$unusual_table

## Cohort codes written more than one way

Stock codes are matched after removing surrounding spaces and converting to upper case; suffixes are kept.

$alias_table

## Cohort products recorded under more than one description

Descriptions are for display only and never used to match products.

$drift_table

## Concentration of the cohort's sales

Over the selection and evaluation years. Shares are of all units: anonymous lines have no customer ID; top customer and top invoice are the largest single customer's and invoice's shares.

$concentration_table

## Calendar

Weeks run Monday to Sunday. The complete weeks run from $first_complete_week to $last_complete_week; the partial weeks at each end are left out. Weeks with no invoice in any country: $closure_weeks. Such a week is left out of history samples and scored as a week with no sales. Selection starts on $selection_first; evaluation runs from $evaluation_first to $evaluation_last.

## Repeated lines

Identical source rows are kept as recorded.

$repeated_table

## Columns of the exported tables

### `policy_comparison.csv`

One row per policy over the evaluation weeks of the primary configuration.

| Column | Meaning |
| --- | --- |
| `policy` | Display name |
| `allocated_units` | Mean start-of-week stock, units |
| `fill_rate` | Share of recorded sales units covered by stock |
| `stockout_rate` | Share of product-weeks with some sales not covered |
| `holding_cost` | Modeled holding cost, £ |
| `shortage_cost` | Modeled shortage cost, £ |
| `total_cost` | Modeled cost, £ |
| `policy_id` | Policy identifier |
| `within_capacity` | Whether start-of-week stock stayed within the limit every week |
| `capacity_units` | The limit on start-of-week stock, units |
| `ordered_units` | Units added over the evaluation weeks |
| `leftover_units` | Mean end-of-week stock, units |
| `reference` | True for a policy shown for reference that ignores the limit |

### `sku_decisions.csv`

One row per cohort product: the stock each policy would set for the week after the evaluation weeks (`decision_week`), with nothing carried in, from the complete weeks with invoices in the primary history window before it.

| Column | Meaning |
| --- | --- |
| `sku` | Stock code |
| `description` | Most frequent description in the history window |
| `unit_price` | Median unit price over the 52 weeks before the decision week, £ |
| `train_mean` | Mean weekly sales over the history window, units |
| `train_std` | Standard deviation of weekly sales over the history window |
| `train_positive_median` | Median of the weeks with sales |
| `train_max` | Largest weekly sales in the history window |
| `active_train_weeks` | Weeks with sales in the history window |
| `proportional_qty` | Proportional-to-recent-mean target |
| `optimized_qty` | Marginal optimizer target |
| `newsvendor_qty` | Unconstrained newsvendor target |
| `spike_ratio` | `train_max` divided by `train_positive_median` (at least 1) |
| `scaled_fractile_qty` | Scaled critical-fractile target |
| `anonymous_share` | Share of the window's units with no customer ID |
| `top_customer_share` | Largest single customer's share of the window's units |
| `top_invoice_share` | Largest single invoice's share of the window's units |
| `decision_week` | Monday of the week the targets are for |

### `forecast_metrics.csv`

One row per history window, scored over the evaluation weeks.

| Column | Meaning |
| --- | --- |
| `method` | History window |
| `wape` | Total absolute error of the window mean divided by total sales |
| `bias` | Total error of the window mean divided by total sales |
| `mae` | Mean absolute error of the window mean per product-week, units |
| `pinball_loss` | Mean pinball loss of the window's critical-ratio quantile per product-week, units |
| `window` | History window identifier |

### `weekly_results.csv`

One row per policy, evaluation week and product in the primary configuration.

| Column | Meaning |
| --- | --- |
| `policy_id` | Policy identifier |
| `week_start` | Monday of the week |
| `sku` | Stock code |
| `price` | Unit price used to decide and score the week, £ |
| `opening` | Stock carried in, units |
| `ordered` | Units added before the week's sales |
| `start` | Start-of-week stock, units |
| `sales` | Recorded sales, units |
| `covered` | Sales covered by stock, units |
| `lost` | Sales not covered, units |
| `closing` | Stock carried out, units |
| `holding_cost` | Holding cost, £ |
| `shortage_cost` | Shortage cost, £ |
| `cost` | Holding plus shortage cost, £ |

### `sensitivity.csv`

One row per scenario: the primary configuration first, then each sensitivity.

| Column | Meaning |
| --- | --- |
| `scenario` | Scenario identifier |
| `label` | Description |
| `window` | History window |
| `closure_weeks` | How weeks without invoices enter history: dropped or kept as zero |
| `capacity_factor` | Factor applied to the cohort's mean weekly sales |
| `holding_rate` | Holding rate, share of price per unit-week |
| `shortage_rate` | Shortage rate, share of price per unit |
| `critical_ratio` | `shortage_rate / (holding_rate + shortage_rate)` |
| `bulk_cap_quantile` | Quantile at which history order quantities are capped, if any |
| `reversals` | Which matched credits remove their sale: prompt, all_exact or none |
| `registry` | Whether registry codes and A invoices are excluded |
| `normalize_case` | Whether stock codes are matched in upper case |
| `capacity_units` | The limit, units |
| `proportional_cost`, `scaled_fractile_cost`, `optimizer_cost`, `optimizer_unit_cost`, `unconstrained_cost` | Modeled cost of each policy, £ |
| `optimizer_vs_scaled_fractile`, `optimizer_vs_proportional` | Optimizer's modeled cost relative to the baseline's, minus one |
| `optimizer_vs_scaled_fractile_low`, `optimizer_vs_scaled_fractile_high`, `optimizer_vs_proportional_low`, `optimizer_vs_proportional_high` | Bootstrap interval of that relative difference |
| `optimizer_vs_scaled_fractile_weeks_won`, `optimizer_vs_scaled_fractile_weeks_lost`, `optimizer_vs_proportional_weeks_won`, `optimizer_vs_proportional_weeks_lost` | Weeks the optimizer cost less / more than the baseline |
| `best_within_capacity` | Lowest-cost policy within the limit |

### `published_bridge.csv`

One row per step from the originally published design.

| Column | Meaning |
| --- | --- |
| `step` | Step identifier |
| `label` | The correction added at this step |
| `train_weeks` | Training weeks |
| `holdout_weeks` | Holdout weeks |
| `first_holdout_week` | Monday of the first holdout week |
| `capacity_units` | The limit at this step, units |
| `skus` | Products selected |
| `skus_added`, `skus_removed` | Products entering or leaving the selection at this step |
| `optimizer_cost`, `scaled_fractile_cost`, `proportional_cost` | Holdout modeled cost of fixed targets, £ |
| `optimizer_vs_proportional`, `optimizer_vs_scaled_fractile` | Optimizer's modeled cost relative to the baseline's, minus one |
| `cohort` | The selected products |

### `reconciliation.csv`

| Column | Meaning |
| --- | --- |
| `sheet` | Source sheet |
| `role` | Role of the row |
| `rows` | Source rows |
| `units` | Signed units |
| `value` | Signed units times price, £ |

### `reversal_pairs.csv`

One row per sale reversed by an equal credit within the window, in every country.

| Column | Meaning |
| --- | --- |
| `sku` | Stock code |
| `customer_id` | Customer |
| `price` | Unit price, £ |
| `units` | Units sold and credited |
| `code_class` | Registry class of the code (merchandise unless listed) |
| `sale_sheet`, `sale_row`, `sale_invoice`, `sale_time`, `sale_country` | The sale line: sheet, spreadsheet row, invoice, time, country |
| `credit_sheet`, `credit_row`, `credit_invoice`, `credit_time`, `credit_country` | The credit line |
| `lag_minutes` | Minutes from sale to credit |
| `prompt` | Whether the credit came within the window |

### `weekly_sales.csv`

One row per cohort product and week of the selection and evaluation years.

| Column | Meaning |
| --- | --- |
| `week_start` | Monday of the week |
| `period` | Selection or evaluation |
| `closure` | Whether the week had no invoice in any country |
| `sku` | Stock code |
| `units` | Sales with every recorded reversal removed, units |
| `units_at_week_close` | Sales as known at the end of the week, the units scored in evaluation |
| `revenue` | Sales value, £ |
