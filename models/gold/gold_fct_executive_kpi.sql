{{ config(materialized='table', tags=['gold']) }}

WITH premium_mom_growth AS (
    SELECT
        party,
        month,
        written_premium,
        mom_growth_pct
    FROM
        {{ ref('gold_fct_premium_mom_growth') }}
),

customer_activity_aggregated AS (
    SELECT
        party,
        activity_month AS month,
        COUNT(DISTINCT user_id) AS active_customers
    FROM
        {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY
        party, activity_month
),

churn_monthly AS (
    SELECT
        month,
        churn_rate
    FROM
        {{ ref('gold_fct_churn_monthly') }}
),

accounting_reconciliation AS (
    SELECT
        party,
        month,
        reconciliation_status
    FROM
        {{ ref('gold_fct_accounting_reconciliation') }}
)

SELECT
    pmg.party,
    pmg.month,
    pmg.written_premium,
    pmg.mom_growth_pct,
    caa.active_customers,
    ROUND(pmg.written_premium / NULLIF(caa.active_customers, 0), 2) AS premium_per_active_customer,
    cm.churn_rate,
    ar.reconciliation_status,
    ROUND(
        (COALESCE(pmg.mom_growth_pct, 0) * 0.4) +
        ((100 - COALESCE(cm.churn_rate, 0)) * 0.4) -
        (CASE WHEN ar.reconciliation_status = 'DISCREPANCY' THEN 20 ELSE 0 END),
        2
    ) AS composite_score,
    current_timestamp AS _created_at
FROM
    premium_mom_growth pmg
LEFT JOIN
    customer_activity_aggregated caa ON pmg.party = caa.party AND pmg.month = caa.month
LEFT JOIN
    churn_monthly cm ON pmg.month = cm.month
LEFT JOIN
    accounting_reconciliation ar ON pmg.party = ar.party AND pmg.month = ar.month