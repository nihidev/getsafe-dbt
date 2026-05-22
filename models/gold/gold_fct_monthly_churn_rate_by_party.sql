{{ config(materialized='table', tags=['gold']) }}

WITH monthly_premiums AS (
    SELECT
        party,
        month,
        written_premium,
        refunded_premium,
        net_premium,
        transaction_count
    FROM {{ ref('gold_fct_monthly_premiums') }}
),

churn_calculations AS (
    SELECT
        party,
        month,
        ROUND(refunded_premium / NULLIF(written_premium, 0)::numeric, 2) AS churn_rate,
        written_premium,
        refunded_premium,
        net_premium,
        transaction_count,
        CASE
            WHEN ROUND(refunded_premium / NULLIF(written_premium, 0)::numeric, 2) > 0.10 THEN TRUE
            ELSE FALSE
        END AS high_churn
    FROM monthly_premiums
)

SELECT
    party,
    month,
    churn_rate,
    written_premium,
    refunded_premium,
    net_premium,
    transaction_count,
    high_churn,
    NOW() AS _created_at
FROM churn_calculations