{{ config(materialized='table', tags=['gold']) }}

WITH cte_premium_mom_growth AS (
    SELECT
        party,
        month,
        written_premium,
        mom_growth_pct
    FROM
        {{ ref('gold_fct_premium_mom_growth') }}
),

cte_churn_monthly AS (
    SELECT
        TO_CHAR(month, 'YYYY-MM') AS month,
        SUM(churned_customers) / NULLIF(SUM(active_start), 0) * 100 AS churn_rate
    FROM
        {{ ref('gold_fct_churn_monthly') }}
    GROUP BY
        TO_CHAR(month, 'YYYY-MM')
),

cte_accounting_reconciliation AS (
    SELECT
        party,
        month,
        reconciliation_status
    FROM
        {{ ref('gold_fct_accounting_reconciliation') }}
),

cte_customer_activity_daily AS (
    SELECT
        product_group AS party,
        activity_month AS month,
        COUNT(DISTINCT user_id) AS active_customers
    FROM
        {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY
        product_group,
        activity_month
)

SELECT
    cte_premium_mom_growth.party,
    cte_premium_mom_growth.month,
    cte_premium_mom_growth.written_premium,
    cte_premium_mom_growth.mom_growth_pct,
    COALESCE(cte_customer_activity_daily.active_customers, 0) AS active_customers,
    ROUND(cte_premium_mom_growth.written_premium / NULLIF(cte_customer_activity_daily.active_customers, 0), 2) AS premium_per_active_customer,
    COALESCE(cte_churn_monthly.churn_rate, 0) AS churn_rate,
    cte_accounting_reconciliation.reconciliation_status,
    ROUND(
        (COALESCE(cte_premium_mom_growth.mom_growth_pct, 0) * 0.4) +
        ((100 - COALESCE(cte_churn_monthly.churn_rate, 0)) * 0.4) -
        (CASE WHEN cte_accounting_reconciliation.reconciliation_status = 'DISCREPANCY' THEN 20 ELSE 0 END),
        2
    ) AS composite_score,
    current_timestamp AS _created_at
FROM
    cte_premium_mom_growth
LEFT JOIN
    cte_churn_monthly ON cte_premium_mom_growth.month = cte_churn_monthly.month
LEFT JOIN
    cte_accounting_reconciliation ON cte_premium_mom_growth.party = cte_accounting_reconciliation.party
    AND cte_premium_mom_growth.month = cte_accounting_reconciliation.month
LEFT JOIN
    cte_customer_activity_daily ON cte_premium_mom_growth.party = cte_customer_activity_daily.party
    AND cte_premium_mom_growth.month = cte_customer_activity_daily.month