{{ config(materialized='table', schema='public_gold', tags=['gold']) }}

WITH monthly_premium AS (
    SELECT
        month,
        party,
        SUM(net_premium) AS total_net_premium
    FROM
        {{ ref('gold_fct_monthly_premiums') }}
    GROUP BY
        month, party
),

total_monthly_premium AS (
    SELECT
        month,
        SUM(total_net_premium) AS total_premium
    FROM
        monthly_premium
    GROUP BY
        month
),

premium_share AS (
    SELECT
        mp.month,
        mp.party,
        mp.total_net_premium,
        tmp.total_premium,
        mp.total_net_premium / NULLIF(tmp.total_premium, 0) AS market_share
    FROM
        monthly_premium mp
    JOIN
        total_monthly_premium tmp ON mp.month = tmp.month
),

hhi_calculation AS (
    SELECT
        month,
        ROUND(SUM(POWER(market_share, 2)), 4) AS hhi
    FROM
        premium_share
    GROUP BY
        month
)

SELECT
    month,
    hhi,
    NOW() AS _created_at
FROM
    hhi_calculation