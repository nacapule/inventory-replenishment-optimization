# Data quality and reconciliation

## Source rows

The workbook has two sheets (Year 2009-2010: 525,461, Year 2010-2011: 541,910; 1,067,371 rows in all). The older sheet repeats the first 22,523 rows of the newer one; that copy is set aside after checking that it is identical, which leaves 1,044,848 rows. Every source row receives exactly one role, so the table sums to the workbook.

| Sheet | Role | Rows | Units | Value |
| --- | --- | ---: | ---: | ---: |
| Year 2009-2010 | overlap | 22,523 | 166,648 | £377,488.45 |
| Year 2009-2010 | accounting_invoice | 3 | 3 | −£136,552.02 |
| Year 2009-2010 | prompt_reversal_credit | 678 | −36,850 | −£97,216.28 |
| Year 2009-2010 | ledger_credit | 9,199 | −164,539 | −£471,274.89 |
| Year 2009-2010 | stock_adjustment | 2,057 | −362,357 | £0.00 |
| Year 2009-2010 | zero_price | 1,452 | 178,167 | £0.00 |
| Year 2009-2010 | prompt_reversal_sale | 678 | 36,850 | £97,216.28 |
| Year 2009-2010 | non_merchandise | 1,673 | 3,366 | £175,103.78 |
| Year 2009-2010 | quarantined | 528 | 2,683 | £225,391.40 |
| Year 2009-2010 | merchandise_sale | 486,670 | 5,608,070 | £9,369,327.91 |
| Year 2010-2011 | accounting_invoice | 3 | 3 | −£11,062.06 |
| Year 2010-2011 | prompt_reversal_credit | 669 | −179,807 | −£305,606.28 |
| Year 2010-2011 | ledger_credit | 8,619 | −97,767 | −£591,206.21 |
| Year 2010-2011 | stock_adjustment | 1,336 | −206,957 | £0.00 |
| Year 2010-2011 | zero_price | 1,179 | 72,603 | £0.00 |
| Year 2010-2011 | prompt_reversal_sale | 669 | 179,807 | £305,606.28 |
| Year 2010-2011 | non_merchandise | 2,015 | 4,034 | £305,876.60 |
| Year 2010-2011 | quarantined | 299 | 7,151 | £64,627.18 |
| Year 2010-2011 | merchandise_sale | 527,121 | 5,397,384 | £9,979,530.42 |

- **overlap**: the older sheet's copy of rows that the newer sheet also holds.
- **accounting_invoice**: invoices numbered with an A (bad-debt adjustments).
- **invalid**: a missing or malformed field, or a quantity that is not a whole, non-zero number.
- **prompt_reversal_sale / prompt_reversal_credit**: a sale and the equal credit that reversed it within 24 hours (same known customer, stock code, price and quantity, credit strictly later).
- **ledger_credit**: every other credit line. Credits are kept in a ledger and never netted against sales.
- **stock_adjustment**: negative quantities without a credit invoice, all at zero price.
- **zero_price**: positive lines with a price of zero.
- **non_merchandise / quarantined**: charges, accounting codes, test codes, vouchers and manual entries listed in `data/code_registry.csv`.
- **merchandise_sale**: everything else, the lines that count as sales.

## The cohort

The 20 products with the highest revenue in the selection year (7 December 2009 to 5 December 2010) among those sold in at least 26 of its weeks, counted as known when the evaluation year began. They and the capacity stay fixed for the whole study.

| SKU | Description | Weeks sold | Units | Revenue |
| --- | --- | ---: | ---: | ---: |
| 22423 | REGENCY CAKESTAND 3 TIER | 38 | 11,431 | £143,492.23 |
| 85123A | WHITE HANGING HEART T-LIGHT HOLDER | 51 | 50,615 | £138,784.69 |
| 85099B | JUMBO BAG RED RETROSPOT | 51 | 43,402 | £79,071.25 |
| 84879 | ASSORTED COLOUR BIRD ORNAMENT | 51 | 39,515 | £63,918.52 |
| 22086 | PAPER CHAIN KIT 50'S CHRISTMAS | 39 | 14,092 | £48,893.19 |
| 47566 | PARTY BUNTING | 50 | 9,156 | £45,718.52 |
| 84347 | ROTATING SILVER ANGELS T-LIGHT HLDR | 31 | 20,543 | £41,988.08 |
| 48138 | DOOR MAT UNION FLAG | 50 | 6,098 | £39,953.86 |
| 21843 | RED RETROSPOT CAKE STAND | 51 | 3,370 | £35,536.05 |
| 21621 | VINTAGE UNION JACK BUNTING | 51 | 4,006 | £34,850.71 |
| 85099F | JUMBO BAG STRAWBERRY | 51 | 18,526 | £34,085.25 |
| 15056N | EDWARDIAN PARASOL NATURAL | 51 | 6,261 | £31,674.73 |
| 21232 | STRAWBERRY CERAMIC TRINKET BOX | 51 | 24,105 | £30,602.81 |
| 22386 | JUMBO BAG PINK WITH WHITE SPOTS | 45 | 15,909 | £30,303.72 |
| 20685 | DOOR MAT RED SPOT | 50 | 4,403 | £30,012.87 |
| 85099C | JUMBO  BAG BAROQUE BLACK WHITE | 51 | 15,966 | £29,760.90 |
| 20725 | LUNCH BAG RED SPOTTY | 51 | 17,095 | £29,452.46 |
| 79321 | CHILLI LIGHTS | 44 | 6,008 | £28,547.79 |
| 21754 | HOME BUILDING BLOCK WORD | 51 | 4,626 | £28,324.06 |
| 21931 | JUMBO STORAGE BAG SUKI | 51 | 14,093 | £28,250.22 |

## From accepted lines to the study (United Kingdom)

| Stage | Lines | Units | Value |
| --- | ---: | ---: | ---: |
| accepted | 937,632 | 9,221,072 | £17,465,896.34 |
| merchandise | 935,153 | 9,209,191 | £16,856,330.94 |
| after_prompt_reversals | 934,107 | 8,999,135 | £16,515,913.43 |
| complete_weeks | 904,260 | 8,723,607 | £15,993,518.56 |
| study_cohort | 42,972 | 597,770 | £1,832,576.50 |

Accepted lines are positive, priced, non-credit sale lines, as the project first counted them. Merchandise drops the registry codes and A invoices. Prompt reversals are then removed, then the partial weeks at both ends of the data. The study cohort is the 20 products over the selection and evaluation years.

## Orders reversed within 24 hours

1,075 sale lines in the United Kingdom (210,153 units) were reversed by an equal credit within 24 hours; 1,347 such pairs exist across all countries. Each pair counts as sales until its credit is recorded and is removed from then on, so a decision never uses a credit recorded after it. 63 of the United Kingdom pairs (4,084 units) involve cohort products. The largest:

| SKU | Units | Sale | Credit | Sale time | Minutes later |
| --- | ---: | --- | --- | --- | ---: |
| 23843 | 80,995 | 581483 | C581484 | 2011-12-09 09:15 | 12 |
| 23166 | 74,215 | 541431 | C541433 | 2011-01-18 10:01 | 16 |
| 22920 | 1,515 | 556484 | C556522 | 2011-06-12 13:17 | 1,324 |
| 47587A | 1,200 | 508333 | C508334 | 2010-05-14 12:00 | 4 |
| 71477 | 1,152 | 529350 | C529352 | 2010-10-28 09:29 | 3 |

Every pair, with both rows' sheet and spreadsheet row, is in `reversal_pairs.csv`.

## Credit lines (United Kingdom)

| Status | Lag | Credits | Units | Value | Re-invoiced | Re-invoiced units |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| no_earlier_equal_sale | unmatched | 10,672 | 75,909 | £383,995.98 | 0 | 0 |
| prompt_reversal | up to 1 hour | 813 | 184,631 | £325,942.59 | 0 | 0 |
| missing_customer | unmatched | 613 | 2,845 | £359,257.27 | 0 | 0 |
| prompt_reversal | 1 to 24 hours | 262 | 25,522 | £40,650.73 | 0 | 0 |
| later_exact_match | 1 to 7 days | 942 | 22,289 | £40,325.18 | 90 | 6,917 |
| later_exact_match | 7 to 28 days | 1,541 | 18,491 | £57,572.18 | 68 | 750 |
| later_exact_match | over 28 days | 1,505 | 26,638 | £61,248.18 | 55 | 3,361 |
| not_negative | unmatched | 1 | −1 | −£373.57 | 0 | 0 |

A credit matches exactly when an earlier sale has the same known customer, stock code, price and quantity; each sale is used once, by the latest earlier match. Matches later than 24 hours stay in the ledger. Re-invoiced counts the later credits followed within 24 hours by an equal sale; that sale may repeat the credited one, so up to that many units may be counted twice in sales.

## Codes that are not merchandise (United Kingdom)

| Code | Class | Action | Lines | Units | Value | Description |
| --- | --- | --- | ---: | ---: | ---: | --- |
| ADJUST | accounting | exclude | 12 | 12 | £6,611.39 | Adjustment by john on 26/01/2010 17 |
| ADJUST2 | accounting | exclude | 3 | 3 | £731.05 | Adjustment by Peter on Jun 25 2010 |
| AMAZONFEE | charge | exclude | 3 | 3 | £20,467.80 | AMAZON FEE |
| B | accounting | exclude | 1 | 1 | £11,062.06 | Adjust bad debt |
| BANK CHARGES | charge | exclude | 33 | 33 | £504.24 | Bank Charges |
| C2 | charge | exclude | 58 | 58 | £2,875.00 | CARRIAGE |
| D | accounting | exclude | 5 | 196 | £397.89 | Discount |
| DOT | charge | exclude | 1,415 | 1,415 | £309,854.11 | DOTCOM POSTAGE |
| GIFT_0001_10 | voucher | exclude | 14 | 15 | £126.21 | Dotcomgiftshop Gift Voucher £10.00 |
| GIFT_0001_20 | voucher | exclude | 26 | 28 | £471.06 | Dotcomgiftshop Gift Voucher £20.00 |
| GIFT_0001_30 | voucher | exclude | 24 | 24 | £610.09 | Dotcomgiftshop Gift Voucher £30.00 |
| GIFT_0001_40 | voucher | exclude | 5 | 5 | £166.09 | Dotcomgiftshop Gift Voucher £40.00 |
| GIFT_0001_50 | voucher | exclude | 6 | 6 | £253.59 | Dotcomgiftshop Gift Voucher £50.00 |
| GIFT_0001_70 | voucher | exclude | 1 | 1 | £59.57 | Dotcomgiftshop Gift Voucher £70.00 |
| GIFT_0001_80 | voucher | exclude | 1 | 1 | £69.56 | Dotcomgiftshop Gift Voucher £80.00 |
| M | manual | quarantine | 763 | 9,835 | £244,868.14 | Manual |
| PADS | manual | quarantine | 16 | 16 | £0.02 | PADS TO MATCH ALL CUSHIONS |
| POST | charge | exclude | 80 | 175 | £10,074.68 | POSTAGE |
| S | accounting | exclude | 3 | 3 | £136.85 | SAMPLES |
| TEST001 | test | exclude | 9 | 50 | £225.00 | This is a test product. |
| TEST002 | test | exclude | 1 | 1 | £1.00 | This is a test product. |

## Retained codes that are not digits plus a letter suffix (United Kingdom)

These codes stay in sales as merchandise.

| Code | Lines | Units | Description |
| --- | ---: | ---: | --- |
| DCGS0003 | 13 | 13 | BOXED GLASS ASHTRAY |
| DCGS0004 | 3 | 3 | HAYNES CAMPER SHOULDER BAG |
| DCGS0037 | 1 | 1 | KEY-RING CORKSCREW |
| DCGS0041 | 1 | 1 | HAYNES MINI-COOPER PLAYING CARDS |
| DCGS0044 | 1 | 1 | HANDZ-OFF CAR FRESHENER |
| DCGS0058 | 28 | 40 | MISO PRETTY  GUM |
| DCGS0062 | 1 | 1 | ROAD-RAGE CAR FRESHENER |
| DCGS0066N | 2 | 2 | NAVY CUDDLES DOG HOODIE |
| DCGS0068 | 1 | 1 | DOGS NIGHT COLLAR |
| DCGS0069 | 5 | 5 | OOH LA LA DOGS COLLAR |
| DCGS0070 | 2 | 2 | CAMOUFLAGE DOG COLLAR |
| DCGS0072 | 3 | 4 | CAT CAMOUFLAGUE COLLAR |
| DCGS0075 | 1 | 1 | CAMOUFLAGUE DOG LEAD |
| DCGS0076 | 13 | 16 | SUNJAR LED NIGHT NIGHT LIGHT |
| DCGSSBOY | 21 | 77 | BOYS PARTY BAG |
| DCGSSGIRL | 23 | 92 | GIRLS PARTY BAG |
| SP1002 | 2 | 5 | KID'S CHALKBOARD/EASEL |

## Cohort codes written more than one way

Stock codes are matched after removing surrounding spaces and converting to upper case; suffixes are kept.

| SKU | Written as | Lines | Units |
| --- | --- | ---: | ---: |
| 15056N | 15056N | 943 | 10,371 |
| 15056N | 15056n | 116 | 173 |
| 85099B | 85099B | 3,778 | 87,768 |
| 85099B | 85099b | 25 | 419 |
| 85099C | 85099C | 1,854 | 29,515 |
| 85099C | 85099c | 10 | 17 |
| 85099F | 85099F | 1,792 | 34,803 |
| 85099F | 85099f | 25 | 201 |
| 85123A | 85123A | 5,361 | 86,648 |
| 85123A | 85123a | 99 | 516 |

## Cohort products recorded under more than one description

Descriptions are for display only and never used to match products.

| SKU | Description | Lines | Units | First seen | Last seen |
| --- | --- | ---: | ---: | --- | --- |
| 20685 | DOOR MAT RED SPOT | 376 | 2,052 | 3 February 2010 | 5 October 2010 |
| 20685 | DOORMAT RED RETROSPOT | 807 | 4,230 | 23 September 2010 | 9 December 2011 |
| 20685 | DOORMAT RED SPOT | 185 | 824 | 28 June 2010 | 10 November 2010 |
| 20685 | RED SPOTTY COIR DOORMAT | 190 | 873 | 1 December 2009 | 1 March 2010 |
| 20725 | LUNCH BAG RED RETROSPOT | 1,692 | 17,581 | 23 September 2010 | 9 December 2011 |
| 20725 | LUNCH BAG RED SPOTTY | 1,132 | 14,603 | 1 December 2009 | 10 November 2010 |
| 21232 | STRAWBERRY CERAMIC TRINKET BOX | 2,229 | 33,389 | 1 December 2009 | 1 December 2011 |
| 21232 | STRAWBERRY CERAMIC TRINKET POT | 114 | 1,091 | 24 October 2011 | 9 December 2011 |
| 21843 | RED RETROSPOT CAKE STAND | 1,031 | 3,714 | 31 March 2010 | 9 December 2011 |
| 21843 | RETRO SPOT CAKE STAND | 294 | 1,090 | 1 December 2009 | 23 May 2010 |
| 22386 | JUMBO BAG PINK POLKADOT | 1,398 | 23,071 | 23 September 2010 | 9 December 2011 |
| 22386 | JUMBO BAG PINK WITH WHITE SPOTS | 761 | 12,132 | 29 January 2010 | 19 November 2010 |
| 48138 | DOOR MAT UNION FLAG | 658 | 3,666 | 15 December 2009 | 13 July 2010 |
| 48138 | DOORMAT UNION FLAG | 946 | 5,950 | 28 June 2010 | 9 December 2011 |
| 85099B | JUMBO BAG RED RETROSPOT | 3,099 | 71,133 | 14 May 2010 | 9 December 2011 |
| 85099B | JUMBO BAG RED WHITE SPOTTY | 507 | 12,191 | 1 December 2009 | 8 June 2010 |
| 85099B | RED RETROSPOT JUMBO BAG | 197 | 4,863 | 31 March 2010 | 1 July 2010 |
| 85123A | CREAM HANGING HEART T-LIGHT HOLDER | 9 | 61 | 8 December 2011 | 9 December 2011 |
| 85123A | WHITE HANGING HEART T-LIGHT HOLDER | 5,451 | 87,103 | 1 December 2009 | 8 December 2011 |

## Concentration of the cohort's sales

Over the selection and evaluation years. Shares are of all units: anonymous lines have no customer ID; top customer and top invoice are the largest single customer's and invoice's shares.

| SKU | Units | Customers | Anonymous | Top customer | Top invoice |
| --- | ---: | ---: | ---: | ---: | ---: |
| 22423 | 21,563 | 1,175 | 10.3% | 9.7% | 1.7% |
| 85123A | 84,317 | 1,423 | 3.0% | 5.3% | 2.3% |
| 85099B | 85,873 | 858 | 4.2% | 10.1% | 1.4% |
| 84879 | 71,661 | 942 | 2.3% | 17.1% | 4.0% |
| 22086 | 30,252 | 836 | 20.0% | 5.4% | 3.4% |
| 47566 | 26,054 | 835 | 18.0% | 2.9% | 1.0% |
| 84347 | 28,417 | 259 | 9.5% | 50.7% | 32.9% |
| 48138 | 9,563 | 651 | 2.0% | 19.9% | 5.2% |
| 21843 | 4,448 | 508 | 7.6% | 10.0% | 4.6% |
| 21621 | 6,701 | 559 | 6.0% | 9.6% | 6.1% |
| 85099F | 34,499 | 507 | 3.5% | 18.3% | 2.6% |
| 15056N | 9,800 | 315 | 4.6% | 12.2% | 6.1% |
| 21232 | 33,302 | 624 | 8.7% | 7.8% | 1.5% |
| 22386 | 34,681 | 546 | 5.9% | 13.6% | 2.3% |
| 20685 | 7,772 | 538 | 5.2% | 22.1% | 3.9% |
| 85099C | 28,595 | 474 | 6.0% | 11.2% | 1.7% |
| 20725 | 31,444 | 733 | 7.7% | 5.0% | 0.8% |
| 79321 | 15,209 | 288 | 6.3% | 12.9% | 3.2% |
| 21754 | 7,140 | 644 | 4.6% | 2.3% | 0.5% |
| 21931 | 26,479 | 488 | 11.8% | 5.3% | 0.8% |

## Calendar

Weeks run Monday to Sunday. The complete weeks run from 7 December 2009 to 4 December 2011; the partial weeks at each end are left out. Weeks with no invoice in any country: the week of 28 December 2009, the week of 27 December 2010. Such a week is left out of history samples and scored as a week with no sales. Selection starts on 7 December 2009; evaluation runs from 6 December 2010 to 4 December 2011.

## Repeated lines

Identical source rows are kept as recorded.

| Sheet | Rows | Repeated rows | Units on repeated rows |
| --- | ---: | ---: | ---: |
| Year 2009-2010 | 525,461 | 6,865 | 18,857 |
| Year 2010-2011 | 541,910 | 5,268 | 13,948 |

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

One row per cohort product: the stock each policy would set for the week after the evaluation year, with nothing carried in.

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
