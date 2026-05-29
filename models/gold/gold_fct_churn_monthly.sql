{{ config(materialized='table', tags=['gold']) }}

WITH user_monthly AS (
    SELECT DISTINCT
        user_id,
        product_group AS party,
        DATE_TRUNC('month', activity_date) AS month
    FROM {{ ref('gold_fct_customer_activity_daily') }}
),

churned_user_list AS (
    SELECT
        prev.user_id,
        prev.party,
        prev.month AS last_active_month
    FROM user_monthly prev
    LEFT JOIN user_monthly curr
        ON  prev.user_id         = curr.user_id
        AND prev.party           = curr.party
        AND curr.month           = prev.month + INTERVAL '1 month'
    WHERE curr.user_id IS NULL
),

churned_users AS (
    SELECT
        party,
        last_active_month + INTERVAL '1 month' AS month,
        COUNT(DISTINCT user_id)                AS churned_customers
    FROM churned_user_list
    GROUP BY party, last_active_month + INTERVAL '1 month'
),

new_users AS (
    SELECT
        product_group AS party,
        DATE_TRUNC('month', acquisition_date) AS month,
        COUNT(DISTINCT user_id)               AS new_customers
    FROM {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY product_group, DATE_TRUNC('month', acquisition_date)
),

churned_premium AS (
    SELECT
        cul.party,
        cul.last_active_month + INTERVAL '1 month' AS month,
        SUM(cad.daily_premium)                     AS churned_premium
    FROM churned_user_list cul
    JOIN {{ ref('gold_fct_customer_activity_daily') }} cad
        ON  cad.user_id                            = cul.user_id
        AND cad.product_group                      = cul.party
        AND DATE_TRUNC('month', cad.activity_date) = cul.last_active_month
    GROUP BY cul.party, cul.last_active_month + INTERVAL '1 month'
),

monthly_active AS (
    SELECT
        product_group AS party,
        DATE_TRUNC('month', activity_date) AS month,
        COUNT(DISTINCT user_id)            AS active_end
    FROM {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY product_group, DATE_TRUNC('month', activity_date)
),

base AS (
    SELECT
        ma.party,
        ma.month,
        LAG(ma.active_end) OVER (PARTITION BY ma.party ORDER BY ma.month) AS active_start,
        ma.active_end,
        COALESCE(cu.churned_customers, 0) AS churned_customers,
        COALESCE(nu.new_customers,     0) AS new_customers,
        COALESCE(cp.churned_premium,   0) AS churned_premium
    FROM monthly_active ma
    LEFT JOIN churned_users cu
        ON ma.party = cu.party AND ma.month = cu.month
    LEFT JOIN new_users nu
        ON ma.party = nu.party AND ma.month = nu.month
    LEFT JOIN churned_premium cp
        ON ma.party = cp.party AND ma.month = cp.month
)

SELECT
    party,
    month,
    active_start,
    active_end,
    churned_customers,
    new_customers,
    ROUND(churned_customers * 100.0 / NULLIF(active_start, 0), 2) AS churn_rate,
    churned_premium,
    ROUND(churned_premium / NULLIF(churned_customers, 0), 2)      AS avg_premium_per_churned_customer,
    current_timestamp                                              AS _created_at
FROM base
ORDER BY party, month