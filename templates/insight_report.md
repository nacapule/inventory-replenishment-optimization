# Inventory replenishment under a capacity limit: results

$headline

![Cumulative weekly difference in modeled cost between the marginal optimizer and each baseline]($figure)

## What was compared

The study follows $cohort_size products sold in the $country through $evaluation_weeks weeks, from $evaluation_first to $evaluation_last. At the start of every week each policy chooses how many units of each product to hold, using only the sales and prices recorded before that week began. Units left at the end of a week are carried into the next week, and sales beyond the units on hand are lost. Replenishment arrives at once (zero lead time).

Total stock at the start of a week may not exceed $capacity units. This is a hypothetical storage limit, counted in units because the data has no product sizes. It equals $capacity_basis over the $open_selection_weeks weeks with invoices in the selection year ($selection_first to $selection_last), rounded to a whole unit. The products are the $cohort_size with the highest revenue that year among those sold in at least $min_active_weeks of its $selection_weeks weeks. The cohort and the limit were fixed before the first evaluation week and are the same for every policy and every scenario, except that the capacity sensitivities apply their own factor to the same mean.

Sales means invoiced merchandise units after removing orders that the same customer reversed with an equal credit within $reversal_hours hours. It stands in for the sales that stock could have covered. The data report, [data_quality.md](data_quality.md), shows how every source line was classified.

## Cost model

Each week costs, for every product, a holding charge on the units left over and a shortage charge on the sales not covered, both in proportion to the product's price. The holding rate h is $holding_pct of the price per unit left at the end of a week; the shortage rate p is $shortage_pct of the price per unit of sales not covered. Both rates are assumptions, not measured costs. Only their ratio, the critical ratio p / (h + p) = $critical_ratio, changes which stock levels are best; their level scales every policy's cost in pounds alike. Modeled cost is this charge summed over the evaluation weeks.

The marginal optimizer chooses start-of-week stock xᵢ for all products together:

    minimize    Σᵢ priceᵢ · ( h · E[(xᵢ − Dᵢ)⁺] + p · E[(Dᵢ − xᵢ)⁺] )
    subject to  Σᵢ xᵢ ≤ C,   xᵢ ≥ carriedᵢ,   xᵢ whole units

Dᵢ is one week's sales of product i, each week of the history window ($window_label; weeks without any invoice are left out) counting equally, and C is the limit. Each product's expected cost is convex in its stock, so giving units one at a time to the product whose next unit lowers expected cost the most reaches the minimum. That stock is optimal for the history window, not a promise about the weeks that follow.

## Policies

| Policy | How it sets start-of-week stock |
| --- | --- |
| Proportional to recent mean | Shares the limit in proportion to each product's mean weekly sales over the history window, then tops carried stock up toward those targets. |
| Scaled critical-fractile | Takes each product's smallest optimal stock on its own (the history window's quantile at the critical ratio), scales the targets down to the limit when their total exceeds it, then tops carried stock up toward them. |
| Marginal optimizer | Solves the problem above, starting from carried stock. |
| Marginal optimizer, equal prices | The same allocation with every price set to one, scored at real prices; it isolates what price weighting contributes. |
| Unconstrained newsvendor | Each product's smallest optimal stock with no limit. A reference only: it uses more space than the limit allows. |

When the targets do not fit beside the carried stock, the free space is shared in proportion to each product's shortfall. Stock is never thrown away, and the first evaluation week starts empty.

## Results

$policy_table

Fill rate is the share of recorded sales units that the stock covered. It is not a service level: sales the retailer could not make were never recorded. SKU-weeks short is the share of product-weeks with some sales not covered.

$comparison_table

The intervals come from a paired moving-block bootstrap over weeks: blocks of $block_weeks consecutive weeks of both policies' costs, resampled $resamples times, with the $confidence percentile interval of the relative difference. The interval checks repeat it with other block lengths. A difference is called clear only when the interval excludes zero.

## By quarter

$quarter_table

## By product

Products are sorted by the optimizer's modeled cost minus the first baseline's, largest first.

$sku_table

## Sensitivities

Each row changes one setting of the primary configuration and keeps the cohort; capacity rows change only the factor applied to the same mean weekly sales. All rows were declared before any result was computed, except where the label says otherwise.

$sensitivity_sentence

$sensitivity_table

## From the published design

$bridge_sentence

$bridge_table

The first row reruns the design this project originally published: the $bridge_sheet sheet alone, every calendar week including the partial ones at both ends, the last $bridge_holdout_weeks weeks held out and all earlier weeks used for training, prices from the whole sheet, $bridge_min_active_weeks active training weeks to qualify, products ranked by training units times price, a limit of $bridge_share of the products' unconstrained quantities (taken with NumPy's "higher" quantile rule), and the same targets every holdout week. Each later row adds one correction, reselects the products and recomputes the limit under the rules then in force. From the complete-weeks row on, the holdout is the last $bridge_holdout_weeks complete weeks and training is every complete week before them.

## History windows as forecasts

The proportional rule uses each window's mean as next week's estimate; the unconstrained newsvendor uses the window's quantile at the critical ratio. Scored against the evaluation weeks' sales:

$forecast_table

WAPE is the total absolute error divided by total sales. Bias is the total error divided by total sales (positive when the estimates ran high). MAE is the mean absolute error per product-week, in units. Pinball loss scores the quantile at the critical ratio, in units per product-week. Lower is better for WAPE, MAE and pinball loss; bias is better the closer it is to zero.

## Largest week

$largest_week

## Next week

`sku_decisions.csv` lists the stock each policy would set for the week starting $decision_week, the first after the evaluation weeks$decision_note, from the complete weeks among the $window_label before it, with nothing carried in.
