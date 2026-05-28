{{ config(materialized='table', tags=['gold']) }}

WITH cte_premium_mom_growth AS (
    SELECT
        party,
        month,
        written_premium,
        mom_growth_pct
    FROM {{ ref('gold_fct_premium_mom_growth') }}
),

cte_churn_monthly_aggregated AS (
    SELECT
        TO_CHAR(month, 'YYYY-MM') AS month,
        SUM(churned_customers) / NULLIF(SUM(active_start), 0) * 100 AS churn_rate
    FROM {{ ref('gold_fct_churn_monthly') }}
    GROUP BY TO_CHAR(month, 'YYYY-MM')
),

cte_accounting_reconciliation AS (
    SELECT
        party,
        month,
        reconciliation_status
    FROM {{ ref('gold_fct_accounting_reconciliation') }}
),

cte_customer_activity_daily_aggregated AS (
    SELECT
        product_group AS party,
        activity_month AS month,
        COUNT(DISTINCT user_id) AS active_customers
    FROM {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY product_group, activity_month
)

SELECT
    pmg.party,
    pmg.month,
    pmg.written_premium,
    pmg.mom_growth_pct,
    cad.active_customers,
    ROUND(pmg.written_premium / NULLIF(cad.active_customers, 0), 2) AS premium_per_active_customer,
    cma.churn_rate,
    ar.reconciliation_status,
    ROUND(
        (COALESCE(pmg.mom_growth_pct, 0) * 0.4) +
        ((100 - COALESCE(cma.churn_rate, 0)) * 0.4) -
        (CASE WHEN ar.reconciliation_status = 'DISCREPANCY' THEN 20 ELSE 0 END),
        2
    ) AS composite_score,
    current_timestamp AS _created_at
FROM cte_premium_mom_growth pmg
LEFT JOIN cte_churn_monthly_aggregated cma ON pmg.month = cma.month
LEFT JOIN cte_accounting_reconciliation ar ON pmg.party = ar.party AND pmg.month = ar.month
LEFT JOIN cte_customer_activity_daily_aggregated cad ON pmg.party = cad.party AND pmg.month = cad.month