{{ config(materialized='table', tags=['gold']) }}

WITH monthly_active AS (
    SELECT
        product_group,
        DATE_TRUNC('month', activity_date) AS month,
        COUNT(DISTINCT user_id) AS active_end
    FROM {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY product_group, DATE_TRUNC('month', activity_date)
),

churned_users AS (
    SELECT
        prev.product_group,
        prev.month AS prev_month,
        curr.month AS curr_month,
        COUNT(DISTINCT prev.user_id) AS churned_customers
    FROM (
        SELECT DISTINCT user_id, product_group, DATE_TRUNC('month', activity_date) AS month
        FROM {{ ref('gold_fct_customer_activity_daily') }}
    ) prev
    LEFT JOIN (
        SELECT DISTINCT user_id, product_group, DATE_TRUNC('month', activity_date) AS month
        FROM {{ ref('gold_fct_customer_activity_daily') }}
    ) curr
    ON prev.user_id = curr.user_id
    AND prev.product_group = curr.product_group
    AND curr.month = prev.month + INTERVAL '1 month'
    WHERE curr.user_id IS NULL
    GROUP BY prev.product_group, prev.month, curr.month
),

new_users AS (
    SELECT
        product_group,
        DATE_TRUNC('month', acquisition_date) AS month,
        COUNT(DISTINCT user_id) AS new_customers
    FROM {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY product_group, DATE_TRUNC('month', acquisition_date)
),

churned_premium AS (
    SELECT
        cad.product_group,
        DATE_TRUNC('month', cad.activity_date) AS month,
        SUM(cad.daily_premium) AS churned_premium
    FROM {{ ref('gold_fct_customer_activity_daily') }} cad
    JOIN churned_users cu
    ON cad.product_group = cu.product_group
    AND DATE_TRUNC('month', cad.activity_date) = cu.prev_month
    GROUP BY cad.product_group, DATE_TRUNC('month', cad.activity_date)
)

SELECT
    ma.product_group,
    ma.month,
    COALESCE(LAG(ma.active_end) OVER (PARTITION BY ma.product_group ORDER BY ma.month), 0) AS active_start,
    ma.active_end,
    COALESCE(cu.churned_customers, 0) AS churned_customers,
    COALESCE(nu.new_customers, 0) AS new_customers,
    ROUND(COALESCE(cu.churned_customers, 0) * 100.0 / NULLIF(LAG(ma.active_end) OVER (PARTITION BY ma.product_group ORDER BY ma.month), 0), 2) AS churn_rate,
    COALESCE(cp.churned_premium, 0) AS churned_premium,
    ROUND(COALESCE(cp.churned_premium, 0) / NULLIF(cu.churned_customers, 0), 2) AS avg_premium_per_churned_customer,
    NOW() AS _created_at
FROM monthly_active ma
LEFT JOIN churned_users cu
ON ma.product_group = cu.product_group
AND ma.month = cu.curr_month
LEFT JOIN new_users nu
ON ma.product_group = nu.product_group
AND ma.month = nu.month
LEFT JOIN churned_premium cp
ON ma.product_group = cp.product_group
AND ma.month = cp.month