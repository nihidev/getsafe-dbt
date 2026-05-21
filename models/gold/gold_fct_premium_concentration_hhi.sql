{{ config(materialized='table', tags=['gold']) }}

WITH filtered_transactions AS (
    SELECT
        party,
        transaction_month,
        premium_amount
    FROM
        {{ ref('silver_transactions') }}
    WHERE
        status = 'completed'
        AND _is_clean = TRUE
),

monthly_premiums AS (
    SELECT
        party,
        transaction_month,
        SUM(premium_amount) AS total_premium
    FROM
        filtered_transactions
    GROUP BY
        party,
        transaction_month
),

total_monthly_premiums AS (
    SELECT
        transaction_month,
        SUM(total_premium) AS total_market_premium
    FROM
        monthly_premiums
    GROUP BY
        transaction_month
),

premium_concentration AS (
    SELECT
        mp.party,
        mp.transaction_month,
        mp.total_premium,
        tmp.total_market_premium,
        (mp.total_premium::NUMERIC / tmp.total_market_premium::NUMERIC) ^ 2 AS hhi_component
    FROM
        monthly_premiums mp
    JOIN
        total_monthly_premiums tmp
    ON
        mp.transaction_month = tmp.transaction_month
),

hhi_index AS (
    SELECT
        transaction_month,
        SUM(hhi_component) AS hhi_index
    FROM
        premium_concentration
    GROUP BY
        transaction_month
)

SELECT
    pc.party,
    pc.transaction_month,
    pc.total_premium,
    pc.total_market_premium,
    hhi.hhi_index
FROM
    premium_concentration pc
JOIN
    hhi_index hhi
ON
    pc.transaction_month = hhi.transaction_month