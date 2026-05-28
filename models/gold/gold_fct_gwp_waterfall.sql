{{ config(materialized='table', tags=['gold']) }}

WITH user_monthly_premium AS (
    SELECT
        user_id,
        product_group,
        TO_CHAR(DATE_TRUNC('month', activity_date), 'YYYY-MM')    AS month,
        TO_CHAR(DATE_TRUNC('month', acquisition_date), 'YYYY-MM') AS acquisition_month,
        SUM(daily_premium)                                        AS premium
    FROM {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY
        user_id,
        product_group,
        TO_CHAR(DATE_TRUNC('month', activity_date), 'YYYY-MM'),
        TO_CHAR(DATE_TRUNC('month', acquisition_date), 'YYYY-MM')
),

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
                 = TO_CHAR(TO_DATE(month, 'YYYY-MM') - INTERVAL '1 month', 'YYYY-MM')
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

lapsed_user_list AS (
    SELECT
        prev.user_id,
        prev.product_group,
        prev.month AS last_active_month
    FROM user_monthly_premium prev
    LEFT JOIN user_monthly_premium curr
        ON  prev.user_id       = curr.user_id
        AND prev.product_group = curr.product_group
        AND curr.month         = TO_CHAR(TO_DATE(prev.month, 'YYYY-MM') + INTERVAL '1 month', 'YYYY-MM')
    WHERE curr.user_id IS NULL
),

lapsed AS (
    SELECT
        lul.product_group,
        TO_CHAR(TO_DATE(lul.last_active_month, 'YYYY-MM') + INTERVAL '1 month', 'YYYY-MM') AS month,
        SUM(prev.premium) AS lapsed_premium
    FROM lapsed_user_list lul
    JOIN user_monthly_premium prev
        ON  lul.user_id = prev.user_id
        AND lul.product_group = prev.product_group
        AND lul.last_active_month = prev.month
    GROUP BY lul.product_group, TO_CHAR(TO_DATE(lul.last_active_month, 'YYYY-MM') + INTERVAL '1 month', 'YYYY-MM')
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