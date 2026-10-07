# Data quality and reconciliation

## Source rows

The workbook's sheets contain $sheet_rows, for $source_rows rows in all. The older sheet contains a copy of the newer sheet's first $overlap_rows rows. After confirming that the copy is identical, it is set aside, leaving $combined_rows rows to classify. Every source row receives exactly one role, including the overlap, so the reconciliation sums to the workbook.

$reconciliation_table

- **overlap**: the older sheet's copy of rows also held in the newer sheet.
- **accounting_invoice**: invoices beginning with A, used for bad-debt adjustments.
- **invalid**: a missing or malformed required field, or a quantity that is not a whole, non-zero number.
- **prompt_reversal_sale / prompt_reversal_credit**: a sale and its equal credit within $reversal_hours hours, with the same known customer, stock code, price and quantity; the credit must be strictly later.
- **ledger_credit**: other credit lines, retained in a ledger and never netted against sales.
- **stock_adjustment**: negative quantities without a credit invoice, at zero price.
- **zero_price**: positive lines priced at zero.
- **non_merchandise**: charges, accounting codes, test codes and vouchers excluded by `data/code_registry.csv`.
- **quarantined**: unidentified manual entries listed in the registry.
- **merchandise_sale**: the remaining positive, priced merchandise lines.

Study **sales** means $country invoiced merchandise units after removing prompt reversals. These sales stand in for the demand that stock could have met. Removal takes effect when the credit is recorded, as explained below.

## The cohort

The **cohort** is the fixed set of $cohort_size products selected by revenue in the selection year, $selection_first to $selection_last. Products qualify if sold in at least $min_active_weeks of that year's weeks. Selection uses only information known when evaluation begins. The cohort and capacity then stay fixed through evaluation.

$selection_table

## From accepted lines to the study ($country)

The stages show which lines enter sales. **Accepted** lines are positive, priced, non-credit lines under the original counting rule. **Merchandise** excludes registry codes and A invoices. The next stages remove prompt reversals, then partial weeks at the workbook's ends. The **study cohort** retains the selected $cohort_size products over the selection and evaluation years.

$stage_table

## Orders reversed within $reversal_hours hours

$country: $prompt_pairs sale lines totaling $prompt_units units have equal credits within the reversal window; $all_prompt_pairs such pairs occur across all countries. Of the $country pairs, $cohort_prompt_pairs involve cohort products, totaling $cohort_prompt_units units.

A pair counts as sales until its credit is recorded and is removed from then on. A decision therefore uses only credits recorded before it. The largest pairs are:

$largest_pairs_table

`reversal_pairs.csv` identifies every pair, including each line's sheet and spreadsheet row.

## Credit lines ($country)

An exact match requires an earlier sale with the same known customer, stock code, price and quantity. Each credit takes the latest unused matching sale; a sale can be matched only once. Matches later than $reversal_hours hours remain in the ledger.

$credit_table

**Re-invoiced** counts later credits followed within $reversal_hours hours by an equal sale. That sale may repeat the credited one, so the reported re-invoiced units bound how many units may be counted twice in sales.

## Codes that are not merchandise ($country)

The registry records each listed code's class and action. Excluded and quarantined codes both stay out of merchandise sales.

$registry_table

## Retained codes that are not digits plus a letter suffix ($country)

These codes remain classified as merchandise.

$unusual_table

## Cohort codes written more than one way

Stock codes are matched after trimming surrounding spaces and converting to upper case. Suffixes are retained.

$alias_table

## Cohort products recorded under more than one description

Descriptions are display labels; they are never used to match products.

$drift_table

## Concentration of the cohort's sales

These shares cover the selection and evaluation years and use all sales units as the denominator. **Anonymous** lines have no customer ID. **Top customer** and **top invoice** are the largest single customer's and invoice's shares.

$concentration_table

## Calendar

Weeks run Monday to Sunday. Complete weeks span $first_complete_week to $last_complete_week; partial weeks at both ends are excluded. Weeks with no invoice in any country: $closure_weeks. They are omitted from history samples and scored as weeks with no sales. Selection starts on $selection_first; evaluation runs from $evaluation_first to $evaluation_last.

## Repeated lines

Identical source rows are retained as recorded.

$repeated_table

## Columns of the exported tables

### `policy_comparison.csv`

One row per policy, summarizing the primary configuration's evaluation weeks.

| Column | Meaning |
| --- | --- |
| `policy` | Policy display name |
| `allocated_units` | Mean total start-of-week stock, units |
| `fill_rate` | Share of recorded sales units covered by stock |
| `stockout_rate` | Share of simulated product-weeks with some recorded sales not covered |
| `holding_cost` | Total modeled holding cost, £ |
| `shortage_cost` | Total modeled shortage cost, £ |
| `total_cost` | Total holding plus shortage cost, £ |
| `policy_id` | Policy identifier |
| `within_capacity` | Whether start-of-week stock stayed within the limit every week |
| `capacity_units` | The limit on start-of-week stock, units |
| `ordered_units` | Units added over the evaluation weeks |
| `leftover_units` | Mean total end-of-week stock, units |
| `reference` | True for the reference that ignores capacity |

### `sku_decisions.csv`

One row per cohort product, with each policy's targets for the week after evaluation (`decision_week`). Targets start with nothing carried in and use complete weeks with invoices in the primary history window before the decision.

| Column | Meaning |
| --- | --- |
| `sku` | Stock code |
| `description` | Most frequent description in the history window |
| `unit_price` | Median unit price over the 52 weeks before the decision week, £ |
| `train_mean` | Mean weekly sales over the history window, units |
| `train_std` | History weekly-sales standard deviation, units |
| `train_positive_median` | Median history week with sales, units |
| `train_max` | Largest history week's sales, units |
| `active_train_weeks` | Weeks with sales in the history window |
| `proportional_qty` | Proportional to recent mean target, units |
| `optimized_qty` | Marginal optimizer target, units |
| `newsvendor_qty` | Unconstrained newsvendor target, units |
| `spike_ratio` | `train_max` divided by `train_positive_median` (the median taken as at least one unit) |
| `scaled_fractile_qty` | Scaled critical-fractile target, units |
| `anonymous_share` | Share of the window's units with no customer ID |
| `top_customer_share` | Largest single customer's share of the window's units |
| `top_invoice_share` | Largest single invoice's share of the window's units |
| `decision_week` | Monday of the week the targets are for |

### `forecast_metrics.csv`

One row per history window, scored over evaluation. The mean supplies the point estimate; the critical-ratio quantile supplies the pinball-loss estimate.

| Column | Meaning |
| --- | --- |
| `method` | History-window display name |
| `wape` | Total absolute error of the window mean divided by total sales |
| `bias` | Total window-mean error, estimate minus sales, divided by total sales |
| `mae` | Window mean's absolute error per product-week, units |
| `pinball_loss` | Critical-ratio quantile's mean pinball loss per product-week, units |
| `window` | History-window identifier |

### `weekly_results.csv`

One row per policy, evaluation week and product in the primary configuration.

| Column | Meaning |
| --- | --- |
| `policy_id` | Policy identifier |
| `week_start` | Monday of the week |
| `sku` | Stock code |
| `price` | Unit price used to decide and score the week, £ |
| `opening` | Stock carried in, units |
| `ordered` | Units added before the week's sales, units |
| `start` | Start-of-week stock, units |
| `sales` | Recorded sales as known at week-end, units |
| `covered` | Recorded sales units covered by simulated stock |
| `lost` | Recorded sales units not covered by simulated stock |
| `closing` | Stock carried out, units |
| `holding_cost` | Modeled holding cost, £ |
| `shortage_cost` | Modeled shortage cost, £ |
| `cost` | Holding plus shortage cost, £ |

### `sensitivity.csv`

One row per scenario: the primary configuration, followed by each sensitivity.

| Column | Meaning |
| --- | --- |
| `scenario` | Scenario identifier |
| `label` | Scenario description |
| `window` | History window |
| `closure_weeks` | Invoice-free weeks: dropped from history or kept as zero |
| `capacity_factor` | Factor applied to the cohort's mean weekly sales |
| `holding_rate` | Holding rate, share of price per unit-week |
| `shortage_rate` | Shortage rate, share of price per unit |
| `critical_ratio` | `shortage_rate / (holding_rate + shortage_rate)` |
| `bulk_cap_quantile` | Quantile at which history order quantities are capped, if any |
| `reversals` | Matched-credit removal rule: prompt, all_exact or none |
| `registry` | Whether registry codes and A invoices are excluded |
| `normalize_case` | Whether stock codes are matched in upper case |
| `capacity_units` | Scenario limit on start-of-week stock, units |
| `proportional_cost` | Proportional to recent mean modeled cost, £ |
| `scaled_fractile_cost` | Scaled critical-fractile modeled cost, £ |
| `optimizer_cost` | Marginal optimizer modeled cost, £ |
| `optimizer_unit_cost` | Equal-price marginal optimizer modeled cost, £ |
| `unconstrained_cost` | Unconstrained newsvendor modeled cost, £ |
| `optimizer_vs_scaled_fractile` | Optimizer cost divided by scaled critical-fractile cost, minus one |
| `optimizer_vs_scaled_fractile_low` | Relative optimizer–scaled difference: lower bootstrap bound |
| `optimizer_vs_scaled_fractile_high` | Relative optimizer–scaled difference: upper bootstrap bound |
| `optimizer_vs_scaled_fractile_weeks_won` | Weeks optimizer cost less than scaled critical-fractile |
| `optimizer_vs_scaled_fractile_weeks_lost` | Weeks optimizer cost more than scaled critical-fractile |
| `optimizer_vs_proportional` | Optimizer cost divided by proportional cost, minus one |
| `optimizer_vs_proportional_low` | Relative optimizer–proportional difference: lower bootstrap bound |
| `optimizer_vs_proportional_high` | Relative optimizer–proportional difference: upper bootstrap bound |
| `optimizer_vs_proportional_weeks_won` | Weeks optimizer cost less than proportional |
| `optimizer_vs_proportional_weeks_lost` | Weeks optimizer cost more than proportional |
| `best_within_capacity` | Lowest-cost feasible policy identifier |

### `published_bridge.csv`

One row per step from the first published design.

| Column | Meaning |
| --- | --- |
| `step` | Step identifier |
| `label` | Rule change added at this step |
| `train_weeks` | Number of training weeks |
| `holdout_weeks` | Number of holdout weeks |
| `first_holdout_week` | Monday of the first holdout week |
| `capacity_units` | The limit at this step, units |
| `skus` | Number of selected products |
| `skus_added` | Stock codes entering the cohort at this step |
| `skus_removed` | Stock codes leaving the cohort at this step |
| `optimizer_cost` | Marginal optimizer holdout cost, fixed targets, £ |
| `scaled_fractile_cost` | Scaled critical-fractile holdout cost, fixed targets, £ |
| `proportional_cost` | Proportional holdout cost, fixed targets, £ |
| `optimizer_vs_proportional` | Optimizer cost divided by proportional cost, minus one |
| `optimizer_vs_scaled_fractile` | Optimizer cost divided by scaled critical-fractile cost, minus one |
| `cohort` | Selected stock codes |

### `reconciliation.csv`

One row per source sheet and classification role, accounting for the whole workbook.

| Column | Meaning |
| --- | --- |
| `sheet` | Source sheet |
| `role` | Classification assigned to the source rows |
| `rows` | Source-row count for this sheet and role |
| `units` | Sum of signed source quantities |
| `value` | Sum of signed quantity times unit price, £ |

### `reversal_pairs.csv`

One row per sale reversed by an equal credit within the reversal window, across all countries.

| Column | Meaning |
| --- | --- |
| `sku` | Stock code |
| `customer_id` | Known customer ID |
| `price` | Unit price, £ |
| `units` | Equal quantities sold and credited, units |
| `code_class` | Registry class of the code (merchandise unless listed) |
| `sale_sheet` | Source sheet of the sale line |
| `sale_row` | Spreadsheet row of the sale line |
| `sale_invoice` | Sale invoice identifier |
| `sale_time` | Sale timestamp |
| `sale_country` | Country on the sale line |
| `credit_sheet` | Source sheet of the credit line |
| `credit_row` | Spreadsheet row of the credit line |
| `credit_invoice` | Credit invoice identifier |
| `credit_time` | Credit timestamp |
| `credit_country` | Country on the credit line |
| `lag_minutes` | Elapsed minutes from sale to credit |
| `prompt` | Whether the credit arrived within the reversal window |

### `weekly_sales.csv`

One row per cohort product and week of the selection and evaluation years.

| Column | Meaning |
| --- | --- |
| `week_start` | Monday of the week |
| `period` | Selection or evaluation |
| `closure` | Whether the week had no invoice in any country |
| `sku` | Stock code |
| `units` | Sales after all recorded reversal removals, units |
| `units_at_week_close` | Sales known at week-end, scored in evaluation, units |
| `revenue` | Sales value after all recorded reversal removals, £ |
