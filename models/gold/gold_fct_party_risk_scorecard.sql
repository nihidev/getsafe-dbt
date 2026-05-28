{{ config(materialized='table', tags=['gold']) }}

WITH base AS (
    SELECT
        pg.party,
        pg.month,
        pg.written_premium,
        pg.mom_growth_pct,
        a.active_customers,
        r.delta_pct,
        r.reconciliation_status
    FROM {{ ref('gold_fct_premium_mom_growth') }} pg
    LEFT JOIN (
        SELECT
            activity_month              AS month,
            COUNT(DISTINCT user_id)     AS active_customers
        FROM {{ ref('gold_fct_customer_activity_daily') }}
        GROUP BY activity_month
    ) a ON pg.month = a.month
    LEFT JOIN {{ ref('gold_fct_accounting_reconciliation') }} r
        ON  pg.party = r.party
        AND pg.month = r.month
),

-- Stage 1: first-level window functions on raw columns
-- Cannot reference these aliases in another window in the same SELECT — must CTE first
with_stage1 AS (
    SELECT
        *,
        AVG(written_premium) OVER (
            PARTITION BY party ORDER BY month
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        )                                                                           AS rolling_3m_avg_premium,
        ROUND((written_premium / NULLIF(active_customers, 0))::numeric, 2)          AS premium_per_customer
    FROM base
),

-- Stage 2: LAG on Stage 1 columns — rolling_3m_avg_premium is now a real column, not nested
with_stage2 AS (
    SELECT
        *,
        LAG(rolling_3m_avg_premium, 3) OVER (PARTITION BY party ORDER BY month)    AS prior_3m_avg,
        LAG(delta_pct)                 OVER (PARTITION BY party ORDER BY month)    AS prev_delta_pct,
        LAG(premium_per_customer)      OVER (PARTITION BY party ORDER BY month)    AS prev_premium_per_customer
    FROM with_stage1
),

-- Stage 3: derived metrics — reference Stage 2 LAG columns (still no nesting)
with_stage3 AS (
    SELECT
        *,
        ROUND(
            ((written_premium - prior_3m_avg) / NULLIF(prior_3m_avg, 0) * 100)::numeric, 2
        )                                                                           AS rolling_3m_growth,
        CASE
            WHEN delta_pct > prev_delta_pct THEN 'WIDENING'
            WHEN delta_pct < prev_delta_pct THEN 'IMPROVING'
            ELSE 'STABLE'
        END                                                                         AS gap_trend,
        ROUND(
            ((premium_per_customer - prev_premium_per_customer)
             / NULLIF(prev_premium_per_customer, 0) * 100)::numeric, 2
        )                                                                           AS premium_per_customer_trend
    FROM with_stage2
),

-- Stage 4: composite score — reference premium_per_customer_trend from Stage 3
with_score AS (
    SELECT
        *,
        ROUND((
            (COALESCE(mom_growth_pct,              0) * 0.35)
            - (COALESCE(delta_pct,                 0) * 0.40)
            + (COALESCE(premium_per_customer_trend, 0) * 0.25)
        )::numeric, 2)                                                              AS composite_risk_score
    FROM with_stage3
),

-- Stage 5: tier — reference composite_risk_score from Stage 4
with_tier AS (
    SELECT
        *,
        CASE
            WHEN composite_risk_score >= 5  THEN 'GREEN'
            WHEN composite_risk_score >= 0  THEN 'AMBER'
            ELSE                                 'RED'
        END                                                                         AS risk_tier
    FROM with_score
),

-- Stage 6: consecutive_red_months — gaps-and-islands reset on non-RED
-- island_grp counts non-RED rows before current row (1 PRECEDING keeps FALSE row in prior island)
islands AS (
    SELECT
        *,
        SUM(CASE WHEN risk_tier != 'RED' THEN 1 ELSE 0 END)
            OVER (PARTITION BY party ORDER BY month
                  ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)                AS island_grp
    FROM with_tier
)

SELECT
    party,
    month,
    written_premium,
    mom_growth_pct,
    ROUND(rolling_3m_avg_premium::numeric, 2)                                      AS rolling_3m_avg_premium,
    rolling_3m_growth,
    reconciliation_status,
    delta_pct,
    prev_delta_pct,
    gap_trend,
    active_customers,
    premium_per_customer,
    prev_premium_per_customer,
    premium_per_customer_trend,
    composite_risk_score,
    risk_tier,
    CASE
        WHEN risk_tier = 'RED'
        THEN ROW_NUMBER() OVER (PARTITION BY party, island_grp ORDER BY month)
        ELSE 0
    END                                                                            AS consecutive_red_months,
    current_timestamp                                                              AS _created_at
FROM islands
ORDER BY party, month
