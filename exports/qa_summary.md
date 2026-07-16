# Data QA Summary

- Source rows: 541,910
- Cancellations / returns excluded: 10,624
- Other invalid rows excluded: 1,181
- Source rows missing descriptions: 1,454
- Accepted positive-sale rows: 530,105
- Accepted rows in United Kingdom: 485,123
- Weekly periods: 54
- Training weeks: 42
- Holdout weeks: 12
- Selected SKUs: 20

Returns and cancellations are excluded from demand rather than silently netted against sales. That makes the demand target interpretable, while the exclusion count remains visible for review.
