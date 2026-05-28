{{ config(materialized='table', tags=['gold']) }}

WITH monthly_premium_data AS (
    SELECT
        party,
        month,
        written_premium,
        LAG(written_premium) OVER (PARTITION BY party ORDER BY month) AS previous_written_premium
    FROM
        {{ ref('gold_fct_monthly_premiums') }}
),

premium_growth AS (
    SELECT
        party,
        month,
        previous_written_premium,
        written_premium,
        ROUND(
            (written_premium - previous_written_premium) / NULLIF(previous_written_premium, 0) * 100,
            2
        ) AS percentage_change
    FROM
        monthly_premium_data
),

cumulative_premium AS (
    SELECT
        party,
        month,
        SUM(written_premium) OVER (PARTITION BY party ORDER BY month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative_written_premium
    FROM
        monthly_premium_data
)

SELECT
    pg.party,
    pg.month,
    pg.previous_written_premium,
    pg.written_premium,
    pg.percentage_change,
    cp.cumulative_written_premium,
    NOW() AS _created_at
FROM
    premium_growth pg
JOIN
    cumulative_premium cp
ON
    pg.party = cp.party AND pg.month = cp.month