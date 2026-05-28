{{ config(materialized='table', tags=['gold']) }}

WITH base_reconciliation AS (
    SELECT
        party,
        month,
        finance_premium,
        accounting_premium,
        reconciliation_status
    FROM {{ ref('gold_fct_accounting_reconciliation') }}
),

delta_calculations AS (
    SELECT
        party,
        month,
        finance_premium,
        accounting_premium,
        finance_premium - accounting_premium AS delta,
        LAG(finance_premium - accounting_premium) OVER (PARTITION BY party ORDER BY month) AS previous_delta,
        CASE 
            WHEN LAG(finance_premium - accounting_premium) OVER (PARTITION BY party ORDER BY month) IS NOT NULL THEN
                (finance_premium - accounting_premium) - LAG(finance_premium - accounting_premium) OVER (PARTITION BY party ORDER BY month)
            ELSE NULL
        END AS delta_change,
        CASE 
            WHEN ABS(finance_premium - accounting_premium) > ABS(LAG(finance_premium - accounting_premium) OVER (PARTITION BY party ORDER BY month)) THEN TRUE 
            ELSE FALSE 
        END AS is_widening,
        ROUND(CAST(ABS(finance_premium - accounting_premium) / NULLIF(accounting_premium, 0) * 100 AS numeric), 2) AS gap_pct,
        CASE 
            WHEN ROUND(CAST(ABS(finance_premium - accounting_premium) / NULLIF(accounting_premium, 0) * 100 AS numeric), 2) < 1 THEN '<1%' 
            WHEN ROUND(CAST(ABS(finance_premium - accounting_premium) / NULLIF(accounting_premium, 0) * 100 AS numeric), 2) < 5 THEN '1–5%' 
            ELSE '>5%' 
        END AS gap_band
    FROM base_reconciliation
),

consecutive_widening_calculations AS (
    SELECT
        party,
        month,
        finance_premium,
        accounting_premium,
        delta,
        previous_delta,
        delta_change,
        is_widening,
        gap_pct,
        gap_band,
        reconciliation_status,
        SUM(CASE WHEN is_widening THEN 1 ELSE 0 END) OVER (PARTITION BY party ORDER BY month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) -
        SUM(CASE WHEN NOT is_widening THEN 1 ELSE 0 END) OVER (PARTITION BY party ORDER BY month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS consecutive_widening
    FROM delta_calculations
)

SELECT
    party,
    month,
    finance_premium,
    accounting_premium,
    delta,
    previous_delta,
    delta_change,
    is_widening,
    consecutive_widening,
    gap_pct,
    gap_band,
    reconciliation_status,
    current_timestamp AS _created_at
FROM consecutive_widening_calculations