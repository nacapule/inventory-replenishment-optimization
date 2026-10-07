# Inventory replenishment under a capacity limit: results

The study compares weekly stock-allocation rules. **Sales** means $country invoiced merchandise units after removing orders the same known customer reversed with an equal credit within $reversal_hours hours. These sales stand in for the demand that stock could have met. [data_quality.md](data_quality.md) explains the source-row classification.

$headline

![Cumulative weekly difference in modeled cost between the marginal optimizer and each baseline]($figure)

## Study and weekly timeline

The evaluation follows $cohort_size products for $evaluation_weeks complete weeks, from $evaluation_first to $evaluation_last. Every Monday, each policy sets start-of-week stock using only sales and prices recorded before that week. Replenishment arrives immediately, with zero lead time. Stock covers the week's sales up to the units on hand; the rest are lost in the simulation. Leftovers carry into the next week. The first evaluation week starts empty.

The **cohort**, the fixed set of products, comprises the $cohort_size highest-revenue products in the selection year ($selection_first to $selection_last) among those sold in at least $min_active_weeks of its $selection_weeks complete weeks. Selection uses only information known when evaluation begins.

**Capacity** is a hypothetical limit of $capacity units on total start-of-week stock, measured in units because the data has no product sizes. It is set to $capacity_basis over the $open_selection_weeks selection weeks with invoices, rounded to a whole unit. The cohort and limit are fixed before evaluation and shared by every policy and scenario, except that capacity sensitivities apply their own factor to the same mean.

Each decision uses the history window ($window_label), omitting weeks without any invoice. Each product's price is its median unit price over the 52 weeks before the decision, used both to allocate stock and to score that week. Evaluation sales reflect reversal credits known at week-end; credits learned later never rewind simulated stock.

## Cost model

Weekly modeled cost combines holding charges on leftovers and shortage charges on recorded sales stock did not cover. The holding rate h is $holding_pct of price per leftover unit-week; the shortage rate p is $shortage_pct of price per uncovered sales unit. Both are assumptions. Only their ratio, the **critical ratio** p / (h + p) = $critical_ratio, changes the stock levels preferred by the history objective. Multiplying both rates by the same amount scales every policy's cost in pounds alike. Total modeled cost sums these charges over evaluation.

The marginal optimizer chooses stock for all products together:

    minimize    Σᵢ priceᵢ · ( h · E[(xᵢ − Dᵢ)⁺] + p · E[(Dᵢ − xᵢ)⁺] )
    subject to  Σᵢ xᵢ ≤ C,   xᵢ ≥ carriedᵢ,   xᵢ whole units

For product i, xᵢ is start-of-week stock, carriedᵢ is stock carried in, priceᵢ is its price, and Dᵢ is one week's sales. C is capacity; h and p are the rates above. The positive-part symbol ⁺ means the larger of the bracketed value and zero; E averages equally over the history weeks. Each product's expected cost is convex, so successive units offer diminishing reductions. Assigning each next unit where it reduces cost most, until none helps or capacity is full, reaches the minimum for that history. “Optimal” refers to this fitted objective.

## Policies

A **newsvendor quantity**, or **critical fractile**, is the smallest stock level at which the history's share of weeks with sales at or below it reaches the critical ratio.

| Policy | How it sets start-of-week stock |
| --- | --- |
| Proportional to recent mean | Shares the limit in proportion to each product's mean weekly sales over the history window. |
| Scaled critical-fractile | Scales the products' newsvendor quantities down to the limit when their total exceeds it. |
| Marginal optimizer | Solves the problem above, starting from carried stock. |
| Marginal optimizer, equal prices | Uses the same optimizer with every price set to one, then scores at real prices to show what price weighting contributes. |
| Unconstrained newsvendor | Uses each product's newsvendor quantity without a shared limit; a reference only. |

The target rules top up carried stock. If their targets do not fit beside it, free space is shared in proportion to each product's shortfall. Stock is never thrown away.

## Results and uncertainty

**Fill rate** is the share of recorded sales units simulated stock covered. It is not a service level: sales the retailer could not make were never recorded. A **SKU** is a product's stock code; **SKU-weeks short** is the share of product-weeks with some sales not covered.

$policy_table

Comparisons subtract the baseline's total modeled cost from the optimizer's; the relative difference divides this by the baseline's cost. Negative values mean the optimizer cost less.

$comparison_table

Uncertainty is measured by a **paired moving-block bootstrap**: both policies' weekly costs are resampled together in blocks of $block_weeks consecutive weeks, $resamples times. The table reports the $confidence percentile interval of the relative difference. It falls back to the difference in pounds only when the relative interval is undefined. The interval checks repeat the calculation with other block lengths. A difference is called **clear** only when its interval excludes zero.

## By quarter

$quarter_table

## By product

Products are sorted by the first cost-difference column, largest first.

$sku_table

## Sensitivities

Each row changes one setting of the primary configuration. The cohort and limit stay fixed, except that capacity rows apply their own factor to the same mean weekly sales. The primary configuration and sensitivities were declared before computing results, except the row labeled otherwise.

$sensitivity_sentence

$sensitivity_table

## From the published design

The bridge begins with the design this project first published. It uses the $bridge_sheet sheet alone, including partial calendar weeks at both ends. The last $bridge_holdout_weeks weeks are held out for evaluation; earlier weeks supply the training history. Products qualify with $bridge_min_active_weeks active training weeks, ranked by training units times price. Prices come from the whole sheet. Capacity is $bridge_share of their unconstrained quantities, calculated with NumPy's “higher” quantile rule. Targets stay fixed throughout the holdout.

Each later row adds one correction, reselects products and recomputes capacity under the rules at that step. From the complete-weeks row onward, the holdout is the last $bridge_holdout_weeks complete weeks; training uses every complete week before them.

$bridge_sentence

$bridge_table

## History windows as forecasts

Each window's mean estimates next week's sales for the proportional rule; its critical-ratio quantile supplies the unconstrained newsvendor quantity. Both are scored against evaluation sales.

$forecast_table

**WAPE** (weighted absolute percentage error) is the history window mean's total absolute error divided by total sales. **Bias** is that mean's total error, estimate minus sales, divided by total sales; positive bias means estimates ran high. **MAE** (mean absolute error) is the mean's absolute error averaged over product-weeks, in units. **Pinball loss** evaluates the window's critical-ratio quantile with an asymmetric absolute error, averaged per product-week: underestimates are weighted by the critical ratio and overestimates by its complement, in units. Lower is better for WAPE, MAE and pinball loss; bias is better the closer it is to zero.

## Largest week

$largest_week

## Next-week targets

`sku_decisions.csv` gives each policy's targets for the week starting $decision_week, the first week after evaluation$decision_note. Targets use the complete weeks with invoices in the history window ($window_label) before that decision, with nothing carried in.
