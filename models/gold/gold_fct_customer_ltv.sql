{{ config(materialized='table', tags=['gold']) }}

WITH customer_ltv AS (
    SELECT
        user_id,
        product_group,
        DATE_TRUNC('month', MIN(acquisition_date)) AS cohort_month,
        DATE_TRUNC('month', MAX(activity_date))    AS last_active_month,
        COUNT(DISTINCT DATE_TRUNC('month', activity_date)) AS active_months,
        SUM(daily_premium)                         AS lifetime_premium
    FROM {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY user_id, product_group
)

SELECT
    user_id,
    product_group,
    cohort_month,
    last_active_month,
    active_months,
    lifetime_premium,
    ROUND(lifetime_premium / NULLIF(active_months, 0), 2)  AS avg_monthly_premium,
    NTILE(10) OVER (ORDER BY lifetime_premium DESC)        AS decile,
    CASE
        WHEN lifetime_premium < 50  THEN '0-50 EUR'
        WHEN lifetime_premium < 200 THEN '50-200 EUR'
        WHEN lifetime_premium < 500 THEN '200-500 EUR'
        ELSE                             '500+ EUR'
    END                                                    AS ltv_bucket,
    current_timestamp                                      AS _created_at
FROM customer_ltv