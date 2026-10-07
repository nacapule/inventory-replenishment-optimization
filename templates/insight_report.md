# Inventory replenishment under a capacity limit: results

The study compares four ways of setting start-of-week stock for $cohort_size products under a shared limit, and one reference without it, replanned every week and scored by modeled holding and shortage cost over $evaluation_weeks weeks. The **marginal optimizer** minimizes that cost over the history it is fitted to. Two simple baselines: the **scaled critical-fractile** rule takes each product's cost-balancing stock level and scales the levels down to fit, and **proportional** allocation shares the limit in proportion to each product's recent mean weekly sales. An equal-price optimizer is a diagnostic and the unconstrained newsvendor a reference (all defined under Policies). A difference is **clear** when its $confidence bootstrap interval excludes zero (see Results and uncertainty).

**Sales** means $country invoiced merchandise units after removing orders that the same known customer reversed with an equal credit within $reversal_hours hours (prompt reversals). These sales stand in for the demand that stock could have met. The data report, [data_quality.md](data_quality.md), explains how every source row was classified.

$headline

![Cumulative weekly difference in modeled cost between the marginal optimizer and each baseline]($figure)

## Study and weekly timeline

The evaluation follows $cohort_size products for $evaluation_weeks complete weeks, from $evaluation_first to $evaluation_last. Every Monday, each policy sets start-of-week stock using only sales and prices recorded before that week. Replenishment arrives at once (zero lead time). Stock covers the week's sales up to the units on hand; the rest are lost. Leftover units carry into the next week. The first evaluation week starts empty.

The **cohort**, the fixed set of products, is the $cohort_size highest-revenue products of the selection year ($selection_first to $selection_last) among those sold in at least $min_active_weeks of its $selection_weeks complete weeks. Selection uses only information known when evaluation begins.

**Capacity** is a hypothetical limit of $capacity units on total start-of-week stock, counted in units because the data has no product sizes. It is $capacity_basis over the $open_selection_weeks selection weeks with invoices, rounded to a whole unit. The cohort and the limit are fixed before evaluation and the same for every policy and scenario, except that capacity sensitivities apply their own factor to the same mean; the unconstrained reference ignores the limit.

Each decision draws on a **history window** of past weeks ($window_label), leaving out weeks without any invoice. Each product's price is its median unit price over the 52 weeks before the decision, used both to allocate stock and to score that week. The sales scored in a week reflect only the reversal credits recorded by its end, so a credit learned later never rewinds simulated stock.

## Cost model

A week's modeled cost is a holding charge on the units left over plus a shortage charge on the recorded sales that stock did not cover. The holding rate h is $holding_pct of the price per unit left at the end of a week; the shortage rate p is $shortage_pct of the price per unit of sales not covered. Both rates are assumptions, not measured costs. Only their ratio, the **critical ratio** p / (h + p) = $critical_ratio, changes which stock levels minimize cost over the history. Multiplying both rates by the same amount scales every policy's cost in pounds alike. Total modeled cost sums these charges over the evaluation weeks.

The marginal optimizer chooses stock for all products together:

    minimize    Σᵢ priceᵢ · ( h · E[(xᵢ − Dᵢ)⁺] + p · E[(Dᵢ − xᵢ)⁺] )
    subject to  Σᵢ xᵢ ≤ C,   xᵢ ≥ carriedᵢ,   xᵢ whole units

For product i, xᵢ is start-of-week stock, carriedᵢ the stock carried in, priceᵢ its price and Dᵢ one week's sales. C is the capacity; h and p are the rates above. (z)⁺ means the larger of z and zero, and E averages over the weeks of the history window, each counting equally. Each product's expected cost is convex in its stock, so each added unit lowers cost by no more than the one before. Giving each next unit to the product where it lowers cost most, until no unit helps or the limit is reached, therefore reaches the minimum for that history. "Optimal" refers to this fitted objective, not to the weeks that follow.

## Policies

A product's **newsvendor quantity** (its **critical fractile**) is the smallest stock level at which the share of history weeks with sales at or below it reaches the critical ratio.

| Policy | How it sets start-of-week stock |
| --- | --- |
| Proportional to recent mean | Shares the limit in proportion to each product's mean weekly sales over the history window. |
| Scaled critical-fractile | Takes each product's newsvendor quantity and scales them all down to the limit when their total exceeds it. |
| Marginal optimizer | Solves the problem above, starting from carried stock. |
| Marginal optimizer, equal prices | The same allocation with every price set to one, scored at real prices: a diagnostic of what price weighting contributes. |
| Unconstrained newsvendor | Each product's newsvendor quantity with no limit: a reference only. |

The proportional and scaled critical-fractile rules set a target for each product and order the gap between carried stock and target. When the gaps together exceed the free space under the limit, that space is shared in proportion to the gaps. No policy discards stock.

## Results and uncertainty

**Fill rate** is the share of recorded sales units that simulated stock covered. It is not a service level, because sales the retailer could not make were never recorded. A **SKU** is a product, identified by its stock code; **SKU-weeks short** is the share of product-weeks with some sales not covered.

$policy_table

Each comparison subtracts the baseline's total modeled cost from the optimizer's; the relative difference divides that by the baseline's cost. Negative values mean the optimizer cost less.

$comparison_table

Uncertainty comes from a **paired moving-block bootstrap**: both policies' weekly costs are resampled together in blocks of $block_weeks consecutive weeks, $resamples times, and the table reports the $confidence percentile interval of the relative difference. When the relative interval is undefined (a baseline cost of zero), the table shows n/a and the verdict uses the interval of the difference in pounds. The interval checks repeat the calculation with other block lengths. A difference is called **clear** only when its interval excludes zero.

## By quarter

$quarter_sentence The last columns show in which part of the year the differences in the comparison table arose.

$quarter_table

## By product

Products are sorted by the first cost-difference column, largest first.

$sku_table

## Sensitivities

Each row changes one factor of the primary configuration: the capacity, the critical ratio, how the history is built, or what counts as a sale. The original-cleaning row switches off all three data corrections together (reversal removal, the code registry and upper-case matching); the all-matched-credits row removes the sale behind every exactly matched credit, not only those within $reversal_hours hours, each from the moment the credit is recorded; the capped-history row caps each invoice's quantity of a product, in the history only, at the percentile its label names, computed over the history window and rounded up. The cohort and the limit stay fixed, except that capacity rows apply their own factor to the same mean weekly sales. All rows were declared before any result was computed, except the one whose label says otherwise.

$sensitivity_sentence

$sensitivity_table

## From the first published design

This **bridge** walks from the design this project first published to the current data rules, one correction per row. The first design uses the $bridge_sheet sheet alone, including the partial calendar weeks at both ends. The last $bridge_holdout_weeks weeks are held out and scored; the earlier weeks are the training history. Products qualify if sold in at least $bridge_min_active_weeks training weeks and are ranked by training units times price. Prices come from the whole sheet. Capacity is $bridge_share of the sum of the products' unconstrained newsvendor quantities, taken with NumPy's "higher" quantile rule. Targets are set once and held through the holdout.

Each later row adds one correction, reselects the products and recomputes capacity under the rules then in force. From the complete-weeks row on, the holdout is the last $bridge_holdout_weeks complete weeks and training is every complete week before them. The scaled critical-fractile column was not part of the first design; it is computed at every row for reference. Every row keeps the single holdout and fixed targets, so the bridge ends at the corrected version of that design, not at the weekly study above.

$bridge_sentence

$bridge_table

## History windows as forecasts

Each window's mean is the proportional rule's estimate of next week's sales; its quantile at the critical ratio is the unconstrained newsvendor quantity. Both are scored against the evaluation weeks' sales. **WAPE** (weighted absolute percentage error) is the window mean's total absolute error divided by total sales. **Bias** is the mean's total error, estimate minus sales, divided by total sales; positive bias means the estimates ran high. **MAE** (mean absolute error) is the mean's absolute error per product-week, in units. **Pinball loss** scores the quantile, per product-week in units: a shortfall below sales is weighted by the critical ratio and an excess by one minus it. Lower is better for WAPE, MAE and pinball loss; bias is better the closer it is to zero. Lower forecast error does not by itself mean lower modeled cost; the history-window rows of the sensitivity table test that.

$forecast_table

## Largest week

Whether the largest remaining spike in a cohort product's weekly sales comes from a credited order:

$largest_week

## Next-week targets

`sku_decisions.csv` gives the targets of every policy except the equal-price diagnostic for the week starting $decision_week, the first week after evaluation$decision_note. They use the complete weeks with invoices in the history window ($window_label) before that week, with nothing carried in.
