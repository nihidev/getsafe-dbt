{{ config(materialized='table', tags=['gold']) }}

WITH monthly_premiums AS (
    SELECT
        month,
        party,
        net_premium,
        written_premium,
        transaction_count
    FROM {{ ref('gold_fct_monthly_premiums') }}
),

total_by_month AS (
    SELECT
        month,
        SUM(net_premium) AS total_net_premium
    FROM monthly_premiums
    GROUP BY month
),

party_shares AS (
    SELECT
        mp.month,
        mp.party,
        mp.net_premium,
        mp.written_premium,
        mp.transaction_count,
        t.total_net_premium,
        mp.net_premium / NULLIF(t.total_net_premium, 0)           AS market_share,
        POWER(mp.net_premium / NULLIF(t.total_net_premium, 0), 2) AS share_squared
    FROM monthly_premiums mp
    JOIN total_by_month t ON mp.month = t.month
),

hhi AS (
    SELECT
        month,
        ROUND(SUM(share_squared) * 10000, 2)                           AS hhi_score,
        COUNT(DISTINCT party)                                           AS active_parties,
        MAX(market_share)                                               AS max_party_share,
        CASE
            WHEN ROUND(SUM(share_squared) * 10000, 2) < 1500  THEN 'competitive'
            WHEN ROUND(SUM(share_squared) * 10000, 2) <= 2500 THEN 'moderately_concentrated'
            ELSE 'highly_concentrated'
        END AS concentration_level,
        CASE WHEN MAX(market_share) > 0.40 THEN TRUE ELSE FALSE END AS dominant_party_flag
    FROM party_shares
    GROUP BY month
)

SELECT
    ps.party,
    ps.month,
    ps.net_premium,
    ps.written_premium,
    ps.total_net_premium,
    ROUND(ps.market_share * 100, 2)  AS market_share_pct,
    h.hhi_score,
    h.active_parties,
    h.concentration_level,
    h.dominant_party_flag,
    ps.transaction_count,
    NOW()                            AS _created_at
FROM party_shares ps
JOIN hhi h ON ps.month = h.month
ORDER BY ps.month ASC, ps.market_share DESC
