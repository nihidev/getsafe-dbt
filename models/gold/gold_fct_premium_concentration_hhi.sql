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
        transaction_month,
        party,
        SUM(premium_amount) AS total_premium
    FROM
        filtered_transactions
    GROUP BY
        transaction_month,
        party
),

total_monthly_premiums AS (
    SELECT
        transaction_month,
        SUM(total_premium) AS total_premium_all_parties
    FROM
        monthly_premiums
    GROUP BY
        transaction_month
),

premium_concentration AS (
    SELECT
        mp.transaction_month,
        mp.party,
        mp.total_premium,
        tmp.total_premium_all_parties,
        (mp.total_premium::NUMERIC / tmp.total_premium_all_parties::NUMERIC) ^ 2 AS hhi_component
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
    hhi.transaction_month,
    hhi.hhi_index
FROM
    hhi_index hhi