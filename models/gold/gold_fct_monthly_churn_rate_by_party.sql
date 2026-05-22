{{ config(materialized='table', tags=['gold']) }}

WITH churned_users AS (
    SELECT
        user_id,
        TO_CHAR(DATE_TRUNC('month', churned_at), 'YYYY-MM') AS churn_month
    FROM
        {{ ref('gold_fct_customer_activity_daily') }}
    WHERE
        churned_at IS NOT NULL
),

monthly_churn_counts AS (
    SELECT
        churn_month AS month,
        COUNT(DISTINCT user_id) AS churned_users_count
    FROM
        churned_users
    GROUP BY
        churn_month
),

monthly_user_counts AS (
    SELECT
        TO_CHAR(DATE_TRUNC('month', activity_date), 'YYYY-MM') AS month,
        COUNT(DISTINCT user_id) AS total_users_count
    FROM
        {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY
        TO_CHAR(DATE_TRUNC('month', activity_date), 'YYYY-MM')
),

churn_rate_by_party AS (
    SELECT
        p.party,
        p.month,
        ROUND((c.churned_users_count::numeric / NULLIF(u.total_users_count, 0)) * 100, 2) AS churn_rate_percentage
    FROM
        {{ ref('gold_fct_monthly_premiums') }} p
    LEFT JOIN
        monthly_churn_counts c
    ON
        p.month = c.month
    LEFT JOIN
        monthly_user_counts u
    ON
        p.month = u.month
)

SELECT
    party,
    month,
    churn_rate_percentage,
    NOW() AS _created_at
FROM
    churn_rate_by_party