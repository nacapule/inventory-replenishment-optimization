# Published-run fixture

`published_run.json` holds the inputs of the originally published comparison, so the
tests can reproduce its costs without the workbook.

It was extracted once from the UCI Online Retail II workbook (sheet `Year 2010-2011`,
United Kingdom) with the project's original pipeline at commit `0e33242`: weekly units
(Monday-start weeks, positive sale lines) for the 20 published SKUs over the 42 training
and 12 holdout weeks, each SKU's median unit price over the whole sheet, and the
published `optimized_qty`, `proportional_qty` and `newsvendor_qty` from
`exports/sku_decisions.csv`. The cost rates (holding 0.05 and shortage 0.30 of price) and
the capacity (7,060 units) are those of the published run. Scored as fixed weekly
targets over the holdout, the optimized and proportional allocations cost £24,208.82 and
£27,971.87.
