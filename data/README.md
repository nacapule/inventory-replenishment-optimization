# Data

The study uses Daqing Chen (2012), *Online Retail II*, from the [UCI Machine Learning Repository](https://archive.ics.uci.edu/dataset/502/online%2Bretail%2Bii), [DOI 10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D). The dataset is licensed under CC BY 4.0.

## Download and workbook

From the repository root, run:

~~~bash
make data
~~~

This downloads the UCI archive and extracts `online_retail_II.xlsx` into `data/raw/`. The command checks the workbook's size and SHA-256 against `configs/published.toml`. The raw workbook is ignored by Git.

The workbook contains invoice lines in `Year 2009-2010` and `Year 2010-2011`, covering December 2009 to December 2011. Lines identify the invoice, stock code, description, quantity, timestamp, unit price, customer and country. The analysis combines both sheets and sets aside their identical overlap.

## What enters the study

Sales means United Kingdom invoiced merchandise units after removing orders the same known customer reversed with an equal credit within 24 hours. These sales stand in for the demand that stock could have met. The study uses complete Monday-to-Sunday weeks. A reversal removes its sale only once the credit is recorded; decisions use no later credits. Other credits remain in a ledger and are never netted against sales.

Stock codes are matched after trimming surrounding spaces and converting to upper case; suffixes are retained. Descriptions are display labels, not product identifiers.

The committed `code_registry.csv` records each listed code's class, action, reason and description. Charges, accounting codes, test codes and vouchers are excluded; unidentified manual entries are quarantined. Both actions keep the lines out of merchandise sales.

The generated [data report](../exports/data_quality.md) reconciles every workbook row to its classification and reports the overlap, reversals, credit ledger, code handling, product selection and calendar. It also defines every column in the documented CSV exports.
