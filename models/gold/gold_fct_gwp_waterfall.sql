-- Template: waterfall
-- Grain: one row per (product_group, month)
-- Slots: {{source_model}}
{{ config(materialized='table', tags=['gold']) }}

WITH user_monthly_premium AS (
    SELECT
        user_id,
        product_group,
        DATE_TRUNC('month', activity_date)    AS month,
        DATE_TRUNC('month', acquisition_date) AS acquisition_month,
        SUM(daily_premium)                    AS premium
    FROM {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY
        user_id,
        product_group,
        DATE_TRUNC('month', activity_date),
        DATE_TRUNC('month', acquisition_date)
),

-- new_business = first calendar month active (= acquisition month)
-- renewal      = active this month AND was active in exactly the prior calendar month
-- reactivation = returned after a gap (not counted in new_business or renewal)
classified AS (
    SELECT
        user_id,
        product_group,
        month,
        premium,
        CASE
            WHEN month = acquisition_month
            THEN 'new_business'
            WHEN LAG(month) OVER (PARTITION BY user_id, product_group ORDER BY month)
                 = month - INTERVAL '1 month'
            THEN 'renewal'
            ELSE 'reactivation'
        END AS transaction_type
    FROM user_monthly_premium
),

active_premiums AS (
    SELECT
        product_group,
        month,
        SUM(CASE WHEN transaction_type = 'new_business' THEN premium ELSE 0 END) AS new_business_premium,
        SUM(CASE WHEN transaction_type = 'renewal'      THEN premium ELSE 0 END) AS renewal_premium
    FROM classified
    GROUP BY product_group, month
),

-- Lapsed: active in month N-1, absent in month N
-- Attribution → month N (the month they failed to renew), premium sourced from month N-1
-- Join on user_id to avoid NULL-side column reuse
lapsed AS (
    SELECT
        prev.product_group,
        prev.month + INTERVAL '1 month' AS month,
        SUM(prev.premium)               AS lapsed_premium
    FROM user_monthly_premium prev
    LEFT JOIN user_monthly_premium curr
        ON  prev.user_id       = curr.user_id
        AND prev.product_group = curr.product_group
        AND curr.month         = prev.month + INTERVAL '1 month'
    WHERE curr.user_id IS NULL
    GROUP BY prev.product_group, prev.month + INTERVAL '1 month'
)

SELECT
    ap.product_group                                                               AS party,
    ap.month,
    ROUND(ap.new_business_premium::numeric, 2)                                     AS new_business_premium,
    ROUND(ap.renewal_premium::numeric, 2)                                          AS renewal_premium,
    ROUND(COALESCE(l.lapsed_premium, 0)::numeric, 2)                               AS lapsed_premium,
    ROUND(
        (ap.new_business_premium + ap.renewal_premium - COALESCE(l.lapsed_premium, 0))
        ::numeric, 2
    )                                                                              AS net_written_premium,
    ROUND(
        COALESCE(l.lapsed_premium, 0) / NULLIF(ap.new_business_premium, 0), 2
    )                                                                              AS lapse_to_new_business_ratio,
    current_timestamp                                                              AS _created_at
FROM active_premiums ap
LEFT JOIN lapsed l
    ON  ap.product_group = l.product_group
    AND ap.month         = l.month
ORDER BY ap.product_group, ap.month