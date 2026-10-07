# Inventory replenishment under a capacity limit: results

The study compares five ways of setting start-of-week stock for 20 products under a shared limit, replanned every week and scored by modeled holding and shortage cost over 52 weeks. The **marginal optimizer** minimizes that cost over the history it is fitted to; the **scaled critical-fractile** and **proportional** rules are simple baselines; an equal-price optimizer and an unconstrained newsvendor serve as a diagnostic and a reference (all defined under Policies). A difference is **clear** when its 95% bootstrap interval excludes zero (see Results and uncertainty).

**Sales** means United Kingdom invoiced merchandise units after removing orders that the same known customer reversed with an equal credit within 24 hours (prompt reversals). These sales stand in for the demand that stock could have met. The data report, [data_quality.md](data_quality.md), explains how every source row was classified.

Over the 52 evaluation weeks, 6 December 2010 to 4 December 2011, the marginal optimizer's modeled cost was 4.0% higher than the scaled critical-fractile rule's (95% interval 0.6% to 8.3% higher; it cost less in 20 of the 52 weeks and more in 32). Against proportional allocation, there was no clear difference: 1.3% lower in total (95% interval from 4.9% lower to 3.3% higher; it cost less in 27 of the 52 weeks and more in 25). The lowest modeled cost within the limit was the scaled critical-fractile rule's (£77,909); the unconstrained newsvendor, which ignores the limit, came to £76,403.

![Cumulative weekly difference in modeled cost between the marginal optimizer and each baseline](cost_difference.svg)

## Study and weekly timeline

The evaluation follows 20 products for 52 complete weeks, from 6 December 2010 to 4 December 2011. Every Monday, each policy sets start-of-week stock using only sales and prices recorded before that week. Replenishment arrives at once (zero lead time). Stock covers the week's sales up to the units on hand; the rest are lost. Leftover units carry into the next week. The first evaluation week starts empty.

The **cohort**, the fixed set of products, is the 20 highest-revenue products of the selection year (7 December 2009 to 5 December 2010) among those sold in at least 26 of its 52 complete weeks. Selection uses only information known when evaluation begins.

**Capacity** is a hypothetical limit of 6,455 units on total start-of-week stock, counted in units because the data has no product sizes. It is the cohort's mean weekly sales (6,455.3 units) over the 51 selection weeks with invoices, rounded to a whole unit. The cohort and the limit are fixed before evaluation and shared by every policy and scenario, except that capacity sensitivities apply their own factor to the same mean.

Each decision draws on a **history window** of past weeks (trailing 52 weeks), leaving out weeks without any invoice. Each product's price is its median unit price over the 52 weeks before the decision, used both to allocate stock and to score that week. The sales scored in a week include only the reversal credits recorded by its end, so a credit learned later never rewinds simulated stock.

## Cost model

A week's modeled cost is a holding charge on the units left over plus a shortage charge on the recorded sales that stock did not cover. The holding rate h is 5.0% of the price per unit left at the end of a week; the shortage rate p is 30.0% of the price per unit of sales not covered. Both rates are assumptions, not measured costs. Only their ratio, the **critical ratio** p / (h + p) = 0.8571 (6/7), changes which stock levels minimize cost over the history. Multiplying both rates by the same amount scales every policy's cost in pounds alike. Total modeled cost sums these charges over the evaluation weeks.

The marginal optimizer chooses stock for all products together:

    minimize    Σᵢ priceᵢ · ( h · E[(xᵢ − Dᵢ)⁺] + p · E[(Dᵢ − xᵢ)⁺] )
    subject to  Σᵢ xᵢ ≤ C,   xᵢ ≥ carriedᵢ,   xᵢ whole units

For product i, xᵢ is start-of-week stock, carriedᵢ the stock carried in, priceᵢ its price and Dᵢ one week's sales. C is the capacity; h and p are the rates above. (z)⁺ means the larger of z and zero, and E averages over the weeks of the history window, each counting equally. Each product's expected cost is convex in its stock, so each added unit lowers cost less than the one before. Giving each next unit to the product where it lowers cost most, until no unit helps or the limit is reached, therefore reaches the minimum for that history. "Optimal" refers to this fitted objective, not to the weeks that follow.

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

| Policy | Within the limit | Modeled cost | Holding | Shortage | Fill rate | SKU-weeks short | Mean start stock | Mean leftover | Units ordered |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Proportional to recent mean | yes | £82,095 | £21,276 | £60,819 | 76.9% | 24.4% | 6,455 | 2,480 | 207,465 |
| Scaled critical-fractile | yes | £77,909 | £21,726 | £56,183 | 77.8% | 24.2% | 6,455 | 2,434 | 209,707 |
| Marginal optimizer | yes | £81,045 | £26,875 | £54,169 | 77.4% | 22.1% | 6,455 | 2,456 | 208,805 |
| Marginal optimizer, equal prices | yes | £79,513 | £21,628 | £57,885 | 77.9% | 22.0% | 6,455 | 2,431 | 209,937 |
| Unconstrained newsvendor (reference, ignores the limit) | no | £76,403 | £45,044 | £31,359 | 88.4% | 10.0% | 9,701 | 5,132 | 239,821 |

Each comparison subtracts the baseline's total modeled cost from the optimizer's; the relative difference divides that by the baseline's cost. Negative values mean the optimizer cost less.

| Comparison | Optimizer | Baseline | Difference | Relative | 95% interval | Interval checks | Weeks lower / higher |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Optimizer vs scaled critical-fractile | £81,045 | £77,909 | £3,135 | +4.0% | +0.6% to +8.3% | 2-week blocks: +1.1% to +7.9%; 8-week blocks: −0.5% to +8.6% | 20 / 32 |
| Optimizer vs proportional to recent mean | £81,045 | £82,095 | −£1,051 | −1.3% | −4.9% to +3.3% | 2-week blocks: −4.4% to +2.6%; 8-week blocks: −6.5% to +4.2% | 27 / 25 |

Uncertainty comes from a **paired moving-block bootstrap**: both policies' weekly costs are resampled together in blocks of 4 consecutive weeks, 10,000 times, and the table reports the 95% percentile interval of the relative difference. It falls back to the difference in pounds only when the relative interval is undefined. The interval checks repeat the calculation with other block lengths. A difference is called **clear** only when its interval excludes zero.

## By quarter

Each quarter is 13 consecutive evaluation weeks. The last columns show in which part of the year the differences in the comparison table arose.

| Quarter | Proportional to recent mean | Scaled critical-fractile | Marginal optimizer | Marginal optimizer, equal prices | Optimizer minus scaled critical-fractile | Optimizer minus proportional to recent mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 (6 December 2010 to 6 March 2011) | £18,539 | £18,028 | £18,219 | £18,198 | £190 | −£320 |
| 2 (7 March 2011 to 5 June 2011) | £17,954 | £16,932 | £16,668 | £16,253 | −£264 | −£1,286 |
| 3 (6 June 2011 to 4 September 2011) | £19,063 | £17,790 | £18,059 | £17,785 | £270 | −£1,004 |
| 4 (5 September 2011 to 4 December 2011) | £26,540 | £25,159 | £28,099 | £27,276 | £2,940 | £1,559 |

## By product

Products are sorted by the first cost-difference column, largest first.

| SKU | Sales units | Proportional to recent mean | Scaled critical-fractile | Marginal optimizer | Marginal optimizer, equal prices | Optimizer minus scaled critical-fractile | Optimizer minus proportional to recent mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 22423 | 10,132 | £6,731 | £6,222 | £8,765 | £6,468 | £2,543 | £2,034 |
| 84347 | 7,874 | £4,823 | £4,600 | £4,913 | £4,842 | £313 | £90 |
| 21843 | 1,078 | £1,257 | £1,282 | £1,537 | £1,229 | £255 | £280 |
| 48138 | 3,465 | £3,521 | £3,508 | £3,681 | £3,567 | £173 | £160 |
| 21754 | 2,514 | £690 | £693 | £829 | £726 | £137 | £140 |
| 21232 | 9,197 | £893 | £836 | £970 | £1,005 | £134 | £77 |
| 79321 | 9,201 | £6,747 | £6,236 | £6,359 | £7,039 | £123 | −£388 |
| 84879 | 32,146 | £4,059 | £4,625 | £4,746 | £4,244 | £121 | £687 |
| 22386 | 18,772 | £3,021 | £2,902 | £3,010 | £2,774 | £108 | −£10 |
| 20725 | 14,449 | £1,190 | £1,225 | £1,302 | £1,179 | £77 | £111 |
| 21621 | 2,695 | £2,916 | £2,951 | £2,973 | £2,781 | £23 | £57 |
| 21931 | 12,386 | £1,289 | £1,325 | £1,314 | £1,052 | −£11 | £25 |
| 85099F | 15,973 | £2,901 | £2,835 | £2,819 | £2,624 | −£16 | −£83 |
| 15056N | 3,539 | £2,320 | £2,159 | £2,132 | £2,233 | −£27 | −£187 |
| 85123A | 33,702 | £7,992 | £8,103 | £8,076 | £8,065 | −£27 | £83 |
| 47566 | 16,898 | £10,631 | £8,344 | £8,284 | £10,157 | −£59 | −£2,347 |
| 85099C | 12,629 | £1,740 | £1,723 | £1,663 | £1,620 | −£60 | −£77 |
| 22086 | 16,160 | £10,220 | £9,104 | £8,980 | £9,216 | −£124 | −£1,240 |
| 20685 | 3,369 | £3,551 | £3,666 | £3,442 | £3,570 | −£224 | −£109 |
| 85099B | 42,471 | £5,603 | £5,572 | £5,250 | £5,123 | −£322 | −£354 |

## Sensitivities

Each row changes one factor of the primary configuration: the capacity, the critical ratio, how the history is built, or what counts as a sale. The original-cleaning row switches off all three data corrections together (reversal removal, the code registry and upper-case matching); the capped-history row caps each invoice's quantity of a product, in the history only, at the percentile its label names, computed over the history window and rounded up. The cohort and the limit stay fixed, except that capacity rows apply their own factor to the same mean weekly sales. All rows were declared before any result was computed, except the one whose label says otherwise.

Across the 11 sensitivities, the marginal optimizer's modeled cost was clearly lower than the scaled critical-fractile rule's in 2, clearly higher in 4 and not clearly different in 5; against proportional allocation, clearly lower in 1, not clearly different in 10 and never clearly higher.

| Scenario | Capacity | Optimizer vs scaled critical-fractile | Optimizer vs proportional to recent mean | Lowest cost within the limit |
| --- | ---: | ---: | ---: | --- |
| Primary configuration | 6,455 | +4.0% (+0.6% to +8.3%) | −1.3% (−4.9% to +3.3%) | Scaled critical-fractile |
| Capacity factor 0.75 | 4,841 | +1.4% (−4.5% to +8.1%) | −1.8% (−8.0% to +5.0%) | Scaled critical-fractile |
| Capacity factor 1.25 | 8,069 | +2.3% (+0.9% to +4.1%) | −3.5% (−5.4% to +0.1%) | Scaled critical-fractile |
| Critical ratio 0.75 | 6,455 | +2.0% (+0.9% to +3.4%) | −0.9% (−3.8% to +1.8%) | Scaled critical-fractile |
| Critical ratio 0.95 | 6,455 | −10.6% (−22.8% to +0.1%) | −5.9% (−12.6% to +1.7%) | Marginal optimizer |
| Critical ratio 0.98 | 6,455 | −20.9% (−33.8% to −10.0%) | −9.6% (−18.3% to −0.8%) | Marginal optimizer |
| History: trailing 13 weeks | 6,455 | −14.1% (−18.6% to −7.6%) | −3.5% (−5.8% to +3.0%) | Marginal optimizer, equal prices |
| History: same 13 weeks a year earlier | 6,455 | +4.5% (−0.2% to +10.4%) | +2.4% (−1.3% to +6.9%) | Scaled critical-fractile |
| Data as originally cleaned | 6,455 | +3.8% (+0.2% to +8.2%) | −1.3% (−4.8% to +3.2%) | Scaled critical-fractile |
| All exactly matched credits removed as known | 6,455 | +3.4% (−0.8% to +7.9%) | −1.6% (−5.9% to +3.2%) | Scaled critical-fractile |
| History capped at each SKU's 99th-percentile order (added after an exploratory result favored it) | 6,455 | +0.7% (−3.0% to +4.5%) | −1.4% (−2.9% to +2.2%) | Scaled critical-fractile |
| Closure weeks kept as zero-sales history | 6,455 | +3.9% (+0.5% to +8.0%) | −1.4% (−4.9% to +3.1%) | Scaled critical-fractile |

## From the first published design

This **bridge** walks from the design this project first published to the current data rules, one correction per row. The first design uses the Year 2010-2011 sheet alone, including the partial calendar weeks at both ends. The last 12 weeks are held out and scored; the earlier weeks are the training history. Products qualify if sold in at least 20 training weeks and are ranked by training units times price. Prices come from the whole sheet. Capacity is 85% of the sum of the products' unconstrained newsvendor quantities, taken with NumPy's "higher" quantile rule. Targets are set once and held through the holdout.

Each later row adds one correction, reselects the products and recomputes capacity under the rules then in force. From the complete-weeks row on, the holdout is the last 12 complete weeks and training is every complete week before them. The scaled critical-fractile column was not part of the first design; it is computed at every row for reference. Every row keeps the single holdout and fixed targets, so the bridge ends at the corrected version of that design, not at the weekly study above.

Rerun as originally designed, the marginal optimizer's modeled cost was 13.5% lower than proportional allocation's. With all 6 corrections applied, it was 3.7% higher than proportional allocation's and 1.3% higher than the scaled critical-fractile rule's. The steps "Prices from the training weeks only" and "Capacity from the smallest optimal quantities" left the products, the capacity and every cost as in the row before.

| Step | Training / holdout weeks | Capacity | Cohort changes | Marginal optimizer | Scaled critical-fractile | Proportional | Optimizer vs proportional |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| Published design | 42 / 12 | 7,060 | none | £24,209 | £23,352 | £27,972 | 13.5% lower |
| Remove sales reversed within 24 hours | 42 / 12 | 7,032 | +20685, −23166 | £24,113 | £23,385 | £23,822 | 1.2% higher |
| Exclude charge, accounting, voucher and manual codes | 42 / 12 | 7,249 | +21175, −DOT | £23,780 | £23,207 | £23,071 | 3.1% higher |
| Merge stock codes that differ only in case | 42 / 12 | 7,250 | none | £23,776 | £23,233 | £23,070 | 3.1% higher |
| Complete weeks only | 40 / 12 | 7,689 | +21621, 22178, 22469, −23298, 48138, 48194 | £24,188 | £23,881 | £23,330 | 3.7% higher |
| Prices from the training weeks only | 40 / 12 | 7,689 | none | £24,188 | £23,881 | £23,330 | 3.7% higher |
| Capacity from the smallest optimal quantities | 40 / 12 | 7,689 | none | £24,188 | £23,881 | £23,330 | 3.7% higher |

## History windows as forecasts

Each window's mean is the proportional rule's estimate of next week's sales; its quantile at the critical ratio is the unconstrained newsvendor quantity. Both are scored against the evaluation weeks' sales. **WAPE** (weighted absolute percentage error) is the window mean's total absolute error divided by total sales. **Bias** is the mean's total error, estimate minus sales, divided by total sales; positive bias means the estimates ran high. **MAE** (mean absolute error) is the mean's absolute error per product-week, in units. **Pinball loss** scores the quantile, per product-week in units: a shortfall below sales is weighted by the critical ratio and an excess by one minus it. Lower is better for WAPE, MAE and pinball loss; bias is better the closer it is to zero. Lower forecast error does not by itself mean lower modeled cost; the history-window rows of the sensitivity table test that.

| History window | WAPE | Bias | MAE (units) | Pinball loss (units) |
| --- | ---: | ---: | ---: | ---: |
| Trailing 52 weeks | 69.4% | 19.2% | 179.3 | 62.3 |
| Trailing 13 weeks | 66.1% | 10.9% | 170.6 | 65.5 |
| Same 13 weeks a year earlier | 73.7% | 24.1% | 190.5 | 67.4 |

## Largest week

The largest spike in a cohort product's weekly sales, relative to its median selling week, and whether a credit matches its largest line:

The largest single week for a cohort product, relative to its typical selling week, was 9,679 units of 84347 (ROTATING SILVER ANGELS T-LIGHT HLDR) in the week of 1 November 2010, 277 times its median selling week of 35 units. Its largest line was invoice 530715 (9,360 units, a known customer). No credit matches that line under the exact-matching rule.

## Next-week targets

`sku_decisions.csv` gives the targets of every policy except the equal-price diagnostic for the week starting 5 December 2011, the first week after evaluation, which is also the workbook's last, partial week. They use the complete weeks with invoices in the history window (trailing 52 weeks) before that week, with nothing carried in.
