-- Independent checks of three published files against the classified ledger.
--
-- src/sqlcheck.py loads these tables into SQLite and runs this file:
--   ledger          one row per source row of both sheets: sheet, source_row, overlap
--                   (the older sheet's copy of the overlap), valid, credit (C invoice),
--                   accounting (A invoice), code_class, code_action (keep, exclude or
--                   quarantine), invoice, sku (stripped and uppercased), customer_id
--                   (NULL when anonymous), price, quantity (NULL when invalid), t (the
--                   timestamp in nanoseconds since 1970, NULL when missing) and country
--   reconciliation  exports/reconciliation.csv
--   reversal_pairs  exports/reversal_pairs.csv
--   weekly_sales    exports/weekly_sales.csv
--   params          window_ns (the reversal window) and country (the study's country)
--
-- Only the ledger's row fields are loaded, not its roles or pairing columns: the roles,
-- the pairing rule and the weekly sums are worked out again here, while the row fields
-- themselves (validity, the invoice and registry flags, normalized codes) are taken as
-- src/data.py reads and normalizes them. The part before the first "-- check:" line
-- builds indexes and views; each check is one query returning the rows where a published
-- file and the ledger disagree, so an empty result is agreement. Money is compared to
-- half a penny, because sums taken in a different order can differ in the last digits;
-- counts and units are compared exactly.

CREATE UNIQUE INDEX ledger_row ON ledger (sheet, source_row);
CREATE INDEX ledger_key ON ledger (customer_id, sku, price, quantity, t);
CREATE INDEX ledger_time ON ledger (t);
CREATE INDEX pair_sale ON reversal_pairs (sale_sheet, sale_row);
CREATE INDEX pair_credit ON reversal_pairs (credit_sheet, credit_row);

-- Lines that may take part in a reversal pair: priced, with a known customer, and not the
-- older sheet's copy of the overlap. A sale is a positive line of an ordinary invoice; a
-- credit is a negative line of a C invoice. Stock code class and country do not matter.
CREATE TEMP VIEW eligible_sale AS
SELECT * FROM ledger
WHERE valid AND NOT overlap AND NOT credit AND NOT accounting
  AND quantity > 0 AND price > 0 AND customer_id IS NOT NULL;

CREATE TEMP VIEW eligible_credit AS
SELECT * FROM ledger
WHERE valid AND NOT overlap AND credit
  AND quantity < 0 AND price > 0 AND customer_id IS NOT NULL;

-- Each row's role by the documented priority, the published pairs being the prompt
-- reversals.
CREATE TEMP VIEW derived_role AS
SELECT l.sheet, l.quantity, l.price,
       CASE
         WHEN l.overlap THEN 'overlap'
         WHEN l.accounting THEN 'accounting_invoice'
         WHEN NOT l.valid THEN 'invalid'
         WHEN l.credit AND EXISTS (SELECT 1 FROM reversal_pairs p
                                   WHERE p.credit_sheet = l.sheet AND p.credit_row = l.source_row)
           THEN 'prompt_reversal_credit'
         WHEN l.credit THEN 'ledger_credit'
         WHEN l.quantity < 0 THEN 'stock_adjustment'
         WHEN l.price = 0 THEN 'zero_price'
         WHEN EXISTS (SELECT 1 FROM reversal_pairs p
                      WHERE p.sale_sheet = l.sheet AND p.sale_row = l.source_row)
           THEN 'prompt_reversal_sale'
         WHEN l.code_action = 'exclude' THEN 'non_merchandise'
         WHEN l.code_action = 'quarantine' THEN 'quarantined'
         ELSE 'merchandise_sale'
       END AS role
FROM ledger l;

-- When each published sale stops counting: its credit's timestamp.
CREATE TEMP VIEW removal AS
SELECT p.sale_sheet AS sheet, p.sale_row AS source_row, MIN(c.t) AS removed_at
FROM reversal_pairs p
JOIN ledger c ON c.sheet = p.credit_sheet AND c.source_row = p.credit_row
GROUP BY p.sale_sheet, p.sale_row;

-- The study's sales lines for the cohort (the stock codes in weekly_sales.csv): ordinary
-- invoice lines of the study's country with a positive quantity and price and a code the
-- registry keeps, each with its Monday and the time its removal becomes known, if any.
CREATE TEMP VIEW cohort_line AS
SELECT l.sku, l.quantity, l.price,
       date(l.t / 1000000000, 'unixepoch', '-6 days', 'weekday 1') AS week_start,
       r.removed_at
FROM ledger l
LEFT JOIN removal r ON r.sheet = l.sheet AND r.source_row = l.source_row
WHERE l.valid AND NOT l.overlap AND NOT l.credit AND NOT l.accounting
  AND l.quantity > 0 AND l.price > 0 AND l.code_action = 'keep'
  AND l.country = (SELECT country FROM params)
  AND l.sku IN (SELECT sku FROM weekly_sales);

-- check: reconciliation
-- Rows, signed units and signed value by sheet and role, from the derived roles, against
-- reconciliation.csv; every sheet and role on either side appears once on both.
WITH derived AS (
  SELECT sheet, role, COUNT(*) AS rows, SUM(COALESCE(quantity, 0)) AS units,
         TOTAL(COALESCE(quantity * price, 0)) AS value
  FROM derived_role
  GROUP BY sheet, role
), published AS (
  SELECT sheet, role, COUNT(*) AS copies, MAX(rows) AS rows, MAX(units) AS units, MAX(value) AS value
  FROM reconciliation
  GROUP BY sheet, role
), keys AS (
  SELECT sheet, role FROM derived UNION SELECT sheet, role FROM published
)
SELECT k.sheet, k.role, p.copies, p.rows AS published_rows, d.rows AS ledger_rows,
       p.units AS published_units, d.units AS ledger_units,
       p.value AS published_value, d.value AS ledger_value
FROM keys k
LEFT JOIN derived d ON d.sheet = k.sheet AND d.role = k.role
LEFT JOIN published p ON p.sheet = k.sheet AND p.role = k.role
WHERE p.copies IS NOT 1 OR p.rows IS NOT d.rows OR p.units IS NOT d.units
   OR NOT COALESCE(ABS(p.value - d.value) <= 0.005, 0);

-- check: pair_validity
-- Every published pair joins an eligible sale and an eligible credit with the same
-- customer, stock code, unit price and quantity, the credit strictly later and no more
-- than the window after the sale, and the file's columns describe those two rows.
SELECT * FROM (
  SELECT p.sale_sheet, p.sale_row, p.credit_sheet, p.credit_row,
         CASE
           WHEN s.source_row IS NULL THEN 'the sale row is not an eligible sale'
           WHEN c.source_row IS NULL THEN 'the credit row is not an eligible credit'
           WHEN s.customer_id <> c.customer_id THEN 'different customers'
           WHEN s.sku <> c.sku THEN 'different stock codes'
           WHEN s.price <> c.price THEN 'different unit prices'
           WHEN s.quantity <> -c.quantity THEN 'different quantities'
           WHEN c.t <= s.t THEN 'the credit is not later than the sale'
           WHEN c.t - s.t > (SELECT window_ns FROM params) THEN 'the credit is outside the window'
           WHEN p.sku IS NOT s.sku OR p.customer_id IS NOT s.customer_id
             OR p.price IS NOT s.price OR p.units IS NOT s.quantity
             OR p.code_class IS NOT s.code_class
             OR p.sale_invoice IS NOT s.invoice OR p.sale_country IS NOT s.country
             OR datetime(p.sale_time) IS NOT datetime(s.t / 1000000000, 'unixepoch')
             OR p.credit_invoice IS NOT c.invoice OR p.credit_country IS NOT c.country
             OR datetime(p.credit_time) IS NOT datetime(c.t / 1000000000, 'unixepoch')
             OR NOT COALESCE(ABS(p.lag_minutes - (c.t - s.t) / 60e9) < 1e-6, 0)
             OR p.prompt IS NOT 'True'
             THEN 'the published columns differ from the ledger rows'
         END AS problem
  FROM reversal_pairs p
  LEFT JOIN eligible_sale s ON s.sheet = p.sale_sheet AND s.source_row = p.sale_row
  LEFT JOIN eligible_credit c ON c.sheet = p.credit_sheet AND c.source_row = p.credit_row
)
WHERE problem IS NOT NULL;

-- check: pair_one_use
-- No sale and no credit appears in more than one published pair.
SELECT 'sale' AS side, sale_sheet AS sheet, sale_row AS source_row, COUNT(*) AS pairs
FROM reversal_pairs
GROUP BY sale_sheet, sale_row
HAVING COUNT(*) > 1
UNION ALL
SELECT 'credit', credit_sheet, credit_row, COUNT(*)
FROM reversal_pairs
GROUP BY credit_sheet, credit_row
HAVING COUNT(*) > 1;

-- check: pair_maximality
-- No eligible credit left out of the pairs could still pair with an eligible sale left
-- out of them: same customer, stock code, unit price and quantity, the sale strictly
-- earlier and within the window.
SELECT c.sheet AS credit_sheet, c.source_row AS credit_row,
       s.sheet AS sale_sheet, s.source_row AS sale_row
FROM eligible_credit c
JOIN eligible_sale s
  ON s.customer_id = c.customer_id AND s.sku = c.sku AND s.price = c.price
 AND s.quantity = -c.quantity
 AND s.t < c.t AND s.t >= c.t - (SELECT window_ns FROM params)
WHERE NOT EXISTS (SELECT 1 FROM reversal_pairs p
                  WHERE p.credit_sheet = c.sheet AND p.credit_row = c.source_row)
  AND NOT EXISTS (SELECT 1 FROM reversal_pairs p
                  WHERE p.sale_sheet = s.sheet AND p.sale_row = s.source_row);

-- check: pair_most_recent
-- Each credit took the most recent sale it could: every eligible sale with the pair's
-- customer, stock code, price and quantity, later than the pair's sale and earlier than
-- its credit, was already taken by a credit no later than this one.
SELECT p.sale_sheet, p.sale_row, p.credit_sheet, p.credit_row,
       o.sheet AS skipped_sheet, o.source_row AS skipped_row
FROM reversal_pairs p
JOIN ledger s ON s.sheet = p.sale_sheet AND s.source_row = p.sale_row
JOIN ledger c ON c.sheet = p.credit_sheet AND c.source_row = p.credit_row
JOIN eligible_sale o
  ON o.customer_id = s.customer_id AND o.sku = s.sku AND o.price = s.price
 AND o.quantity = s.quantity AND o.t > s.t AND o.t < c.t
WHERE NOT EXISTS (
  SELECT 1
  FROM reversal_pairs q
  JOIN ledger taken ON taken.sheet = q.credit_sheet AND taken.source_row = q.credit_row
  WHERE q.sale_sheet = o.sheet AND q.sale_row = o.source_row AND taken.t <= c.t
);

-- check: weekly_sales
-- For every Monday from the first to the last week in weekly_sales.csv and every cohort
-- stock code, exactly one published row whose units are the week's sales with every
-- published pair removed, units_at_week_close those with only the removals known before
-- the next Monday, revenue the removed-pairs units times their prices, and closure true
-- exactly when the source has no row at all that week.
WITH RECURSIVE week(week_start) AS (
  SELECT MIN(week_start) FROM weekly_sales
  UNION ALL
  SELECT date(week_start, '+7 days') FROM week
  WHERE week_start < (SELECT MAX(week_start) FROM weekly_sales)
), closure AS (
  SELECT week_start,
         NOT EXISTS (
           SELECT 1 FROM ledger l
           WHERE NOT l.overlap
             AND l.t >= CAST(strftime('%s', week.week_start) AS INTEGER) * 1000000000
             AND l.t < CAST(strftime('%s', week.week_start, '+7 days') AS INTEGER) * 1000000000
         ) AS closed
  FROM week
), cell AS (
  SELECT week.week_start, cohort.sku FROM week, (SELECT DISTINCT sku FROM weekly_sales) cohort
  UNION
  SELECT week_start, sku FROM weekly_sales
), published AS (
  SELECT week_start, sku, COUNT(*) AS copies, MAX(units) AS units,
         MAX(units_at_week_close) AS units_at_week_close, MAX(revenue) AS revenue,
         MAX(closure) AS closure
  FROM weekly_sales
  GROUP BY week_start, sku
), computed AS (
  SELECT week_start, sku,
         SUM(CASE WHEN removed_at IS NULL THEN quantity ELSE 0 END) AS units,
         SUM(CASE WHEN removed_at IS NULL
                    OR removed_at >= CAST(strftime('%s', week_start, '+7 days') AS INTEGER) * 1000000000
                  THEN quantity ELSE 0 END) AS units_at_week_close,
         TOTAL(CASE WHEN removed_at IS NULL THEN quantity * price ELSE 0 END) AS revenue
  FROM cohort_line
  GROUP BY week_start, sku
)
SELECT x.week_start, x.sku, p.copies,
       p.units AS published_units, COALESCE(k.units, 0) AS ledger_units,
       p.units_at_week_close AS published_at_close, COALESCE(k.units_at_week_close, 0) AS ledger_at_close,
       p.revenue AS published_revenue, COALESCE(k.revenue, 0) AS ledger_revenue,
       p.closure AS published_closure, w.closed AS ledger_closure
FROM cell x
LEFT JOIN published p ON p.week_start = x.week_start AND p.sku = x.sku
LEFT JOIN computed k ON k.week_start = x.week_start AND k.sku = x.sku
LEFT JOIN closure w ON w.week_start = x.week_start
WHERE p.copies IS NOT 1 OR w.week_start IS NULL OR strftime('%w', x.week_start) IS NOT '1'
   OR p.units IS NOT COALESCE(k.units, 0)
   OR p.units_at_week_close IS NOT COALESCE(k.units_at_week_close, 0)
   OR NOT COALESCE(ABS(p.revenue - COALESCE(k.revenue, 0)) <= 0.005, 0)
   OR p.closure IS NOT (CASE WHEN w.closed THEN 'True' ELSE 'False' END);
