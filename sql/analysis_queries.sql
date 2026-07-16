-- The analysis writes selected weekly demand, SKU decisions, forecast metrics,
-- and policy results to exports/replenishment.db.

-- Compare allocation policies.
SELECT
    policy,
    allocated_units,
    ROUND(fill_rate * 100, 2) AS fill_rate_pct,
    ROUND(stockout_rate * 100, 2) AS stockout_sku_weeks_pct,
    ROUND(total_cost, 2) AS modeled_cost
FROM policy_results
ORDER BY total_cost;

-- Products with the largest change from proportional allocation.
SELECT
    sku,
    description,
    proportional_qty,
    optimized_qty,
    optimized_qty - proportional_qty AS unit_shift,
    ROUND(train_mean, 2) AS train_mean,
    ROUND(train_std, 2) AS train_std,
    ROUND(train_positive_median, 2) AS positive_week_median,
    ROUND(train_max, 2) AS maximum_week,
    ROUND(spike_ratio, 1) AS max_to_typical_ratio
FROM sku_decisions
ORDER BY ABS(optimized_qty - proportional_qty) DESC
LIMIT 15;

-- Large training-period spikes to review.
SELECT
    sku,
    description,
    ROUND(train_positive_median, 2) AS positive_week_median,
    ROUND(train_max, 2) AS maximum_week,
    ROUND(spike_ratio, 1) AS max_to_typical_ratio
FROM sku_decisions
WHERE spike_ratio >= 10
ORDER BY spike_ratio DESC;

-- Total weekly demand across the selected products.
SELECT
    week,
    SUM(demand) AS portfolio_units
FROM weekly_demand
GROUP BY week
ORDER BY week;

-- Forecast ranking. WAPE makes errors comparable across SKU scales.
SELECT
    method,
    ROUND(wape * 100, 2) AS wape_pct,
    ROUND(bias * 100, 2) AS bias_pct,
    ROUND(mae, 2) AS mae
FROM forecast_metrics
ORDER BY wape;
