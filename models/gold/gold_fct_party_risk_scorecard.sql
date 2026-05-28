{{ config(materialized='table', tags=['gold']) }}

WITH premium_growth AS (
    SELECT
        party,
        month,
        written_premium,
        mom_growth_pct,
        cumulative_written_premium
    FROM {{ ref('gold_fct_premium_mom_growth') }}
),

active_by_month AS (
    SELECT
        activity_month                  AS month,
        COUNT(DISTINCT user_id)         AS active_customers
    FROM {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY activity_month
),

reconciliation AS (
    SELECT
        party,
        month,
        delta,
        delta_pct,
        reconciliation_status
    FROM {{ ref('gold_fct_accounting_reconciliation') }}
)

SELECT
    pg.party,
    pg.month,
    pg.written_premium,
    pg.mom_growth_pct,
    AVG(pg.written_premium) OVER (PARTITION BY pg.party ORDER BY pg.month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS rolling_3m_avg_premium,
    ROUND((pg.written_premium - LAG(AVG(pg.written_premium) OVER (PARTITION BY pg.party ORDER BY pg.month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 3) OVER (PARTITION BY pg.party ORDER BY pg.month)) / NULLIF(LAG(AVG(pg.written_premium) OVER (PARTITION BY pg.party ORDER BY pg.month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 3) OVER (PARTITION BY pg.party ORDER BY pg.month), 0) * 100, 2) AS rolling_3m_growth,
    r.reconciliation_status,
    r.delta_pct,
    LAG(r.delta_pct) OVER (PARTITION BY pg.party ORDER BY pg.month) AS prev_delta_pct,
    CASE WHEN r.delta_pct > LAG(r.delta_pct) OVER (PARTITION BY pg.party ORDER BY pg.month) THEN 'WIDENING' WHEN r.delta_pct < LAG(r.delta_pct) OVER (PARTITION BY pg.party ORDER BY pg.month) THEN 'IMPROVING' ELSE 'STABLE' END AS gap_trend,
    a.active_customers,
    ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2) AS premium_per_customer,
    LAG(ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2)) OVER (PARTITION BY pg.party ORDER BY pg.month) AS prev_premium_per_customer,
    ROUND(((ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2) - LAG(ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2)) OVER (PARTITION BY pg.party ORDER BY pg.month)) / NULLIF(LAG(ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2)) OVER (PARTITION BY pg.party ORDER BY pg.month), 0) * 100)::numeric, 2) AS premium_per_customer_trend,
    ROUND(((COALESCE(pg.mom_growth_pct, 0) * 0.35) - (COALESCE(r.delta_pct, 0) * 0.40) + (COALESCE(ROUND(((ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2) - LAG(ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2)) OVER (PARTITION BY pg.party ORDER BY pg.month)) / NULLIF(LAG(ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2)) OVER (PARTITION BY pg.party ORDER BY pg.month), 0) * 100)::numeric, 2), 0) * 0.25))::numeric, 2) AS composite_risk_score,
    CASE WHEN ROUND(((COALESCE(pg.mom_growth_pct, 0) * 0.35) - (COALESCE(r.delta_pct, 0) * 0.40) + (COALESCE(ROUND(((ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2) - LAG(ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2)) OVER (PARTITION BY pg.party ORDER BY pg.month)) / NULLIF(LAG(ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2)) OVER (PARTITION BY pg.party ORDER BY pg.month), 0) * 100)::numeric, 2), 0) * 0.25))::numeric, 2) >= 5 THEN 'GREEN' WHEN ROUND(((COALESCE(pg.mom_growth_pct, 0) * 0.35) - (COALESCE(r.delta_pct, 0) * 0.40) + (COALESCE(ROUND(((ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2) - LAG(ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2)) OVER (PARTITION BY pg.party ORDER BY pg.month)) / NULLIF(LAG(ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2)) OVER (PARTITION BY pg.party ORDER BY pg.month), 0) * 100)::numeric, 2), 0) * 0.25))::numeric, 2) >= 0 THEN 'AMBER' ELSE 'RED' END AS risk_tier,
    SUM(CASE WHEN ROUND(((COALESCE(pg.mom_growth_pct, 0) * 0.35) - (COALESCE(r.delta_pct, 0) * 0.40) + (COALESCE(ROUND(((ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2) - LAG(ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2)) OVER (PARTITION BY pg.party ORDER BY pg.month)) / NULLIF(LAG(ROUND((pg.written_premium / NULLIF(a.active_customers, 0))::numeric, 2)) OVER (PARTITION BY pg.party ORDER BY pg.month), 0) * 100)::numeric, 2), 0) * 0.25))::numeric, 2) < 0 THEN 1 ELSE 0 END) OVER (PARTITION BY pg.party ORDER BY pg.month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS consecutive_red_months,
    current_timestamp AS _created_at
FROM premium_growth pg
LEFT JOIN active_by_month a ON pg.month = a.month
LEFT JOIN reconciliation r ON pg.party = r.party AND pg.month = r.month
ORDER BY pg.party, pg.month