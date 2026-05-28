{{ config(materialized='table', tags=['gold']) }}

WITH user_monthly AS (
    SELECT
        user_id,
        product_group,
        DATE_TRUNC('month', activity_date) AS month
    FROM
        {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY
        user_id,
        product_group,
        DATE_TRUNC('month', activity_date)
),

churned_user_list AS (
    SELECT
        um.user_id,
        um.product_group,
        DATE_TRUNC('month', MAX(um.month)) AS last_active_month
    FROM
        user_monthly um
    LEFT JOIN
        {{ ref('gold_fct_customer_activity_daily') }} curr
    ON
        um.user_id = curr.user_id
        AND um.product_group = curr.product_group
        AND DATE_TRUNC('month', curr.activity_date) = um.month + INTERVAL '1 month'
    WHERE
        curr.user_id IS NULL
    GROUP BY
        um.user_id,
        um.product_group
),

customer_ltv AS (
    SELECT
        cad.user_id,
        cad.product_group,
        DATE_TRUNC('month', MIN(cad.acquisition_date)) AS cohort_month,
        DATE_TRUNC('month', MAX(cad.activity_date)) AS last_active_month,
        COUNT(DISTINCT DATE_TRUNC('month', cad.activity_date)) AS active_months,
        SUM(cad.daily_premium) AS lifetime_premium
    FROM
        {{ ref('gold_fct_customer_activity_daily') }} cad
    GROUP BY
        cad.user_id,
        cad.product_group
),

top_10_pct AS (
    SELECT
        user_id,
        product_group,
        lifetime_premium,
        NTILE(10) OVER (ORDER BY lifetime_premium DESC) AS decile
    FROM
        customer_ltv
),

ltv_bucket_distribution AS (
    SELECT
        product_group,
        ltv_bucket,
        COUNT(user_id) AS customer_count
    FROM (
        SELECT
            cl.user_id,
            cl.product_group,
            CASE
                WHEN cl.lifetime_premium < 50 THEN '0–50 EUR'
                WHEN cl.lifetime_premium < 200 THEN '50–200 EUR'
                WHEN cl.lifetime_premium < 500 THEN '200–500 EUR'
                ELSE '500+ EUR'
            END AS ltv_bucket
        FROM
            customer_ltv cl
    ) sub
    GROUP BY
        product_group,
        ltv_bucket
)

SELECT
    cl.user_id,
    cl.product_group,
    cl.cohort_month,
    cl.last_active_month,
    cl.active_months,
    cl.lifetime_premium,
    ROUND(cl.lifetime_premium / NULLIF(cl.active_months, 0), 2) AS avg_monthly_premium,
    CASE
        WHEN cl.lifetime_premium < 50 THEN '0–50 EUR'
        WHEN cl.lifetime_premium < 200 THEN '50–200 EUR'
        WHEN cl.lifetime_premium < 500 THEN '200–500 EUR'
        ELSE '500+ EUR'
    END AS ltv_bucket,
    current_timestamp AS _created_at
FROM
    customer_ltv cl

UNION ALL

SELECT
    NULL AS user_id,
    NULL AS product_group,
    NULL AS cohort_month,
    NULL AS last_active_month,
    NULL AS active_months,
    SUM(CASE WHEN decile = 1 THEN lifetime_premium ELSE 0 END) AS top_10_pct_premium,
    ROUND(SUM(CASE WHEN decile = 1 THEN lifetime_premium ELSE 0 END) / NULLIF(SUM(lifetime_premium), 0) * 100, 2) AS share_pct,
    NULL AS ltv_bucket,
    current_timestamp AS _created_at
FROM
    top_10_pct

UNION ALL

SELECT
    NULL AS user_id,
    product_group,
    NULL AS cohort_month,
    NULL AS last_active_month,
    NULL AS active_months,
    NULL AS lifetime_premium,
    NULL AS avg_monthly_premium,
    ltv_bucket,
    current_timestamp AS _created_at
FROM
    ltv_bucket_distribution