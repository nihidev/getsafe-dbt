{{ config(materialized='table', tags=['gold']) }}

WITH user_monthly AS (
    SELECT
        DISTINCT user_id,
        product_group,
        DATE_TRUNC('month', activity_date)    AS activity_month,
        DATE_TRUNC('month', acquisition_date) AS cohort_month
    FROM {{ ref('gold_fct_customer_activity_daily') }}
),

-- Cohort size = all users acquired in that month, regardless of when their
-- policy started. Counting only month-0 active users causes NULL cohort_size
-- for cohorts where started_at lags acquisition_date (e.g. underwriting delay).
cohort_size AS (
    SELECT
        cohort_month,
        product_group,
        COUNT(DISTINCT user_id) AS cohort_size
    FROM user_monthly
    GROUP BY cohort_month, product_group
),

active_customers AS (
    SELECT
        cohort_month,
        product_group,
        activity_month,
        COUNT(DISTINCT user_id) AS active_customers
    FROM user_monthly
    GROUP BY cohort_month, product_group, activity_month
),

cohort_retention AS (
    SELECT
        ac.cohort_month,
        ac.product_group,
        ac.activity_month,
        cs.cohort_size,
        ac.active_customers,
        (
            (DATE_PART('year',  ac.activity_month) - DATE_PART('year',  ac.cohort_month)) * 12 +
            (DATE_PART('month', ac.activity_month) - DATE_PART('month', ac.cohort_month))
        )::INTEGER AS months_since_acquisition
    FROM active_customers ac
    LEFT JOIN cohort_size cs
        ON  ac.cohort_month   = cs.cohort_month
        AND ac.product_group  = cs.product_group
)

SELECT
    cohort_month,
    product_group,
    months_since_acquisition,
    cohort_size,
    active_customers,
    ROUND(
        (100.0 * active_customers / NULLIF(cohort_size, 0))::numeric, 1
    ) AS retention_rate,
    current_timestamp AS _created_at
FROM cohort_retention
ORDER BY cohort_month, product_group, months_since_acquisition;
