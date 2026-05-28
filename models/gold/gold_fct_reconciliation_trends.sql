{{ config(materialized='table', tags=['gold']) }}

WITH base AS (
    SELECT
        party,
        month,
        finance_premium,
        accounting_premium,
        reconciliation_status,
        finance_premium - accounting_premium                                        AS delta,
        ROUND(
            (ABS(finance_premium - accounting_premium)
            / NULLIF(accounting_premium, 0) * 100)::numeric, 2
        )                                                                           AS gap_pct
    FROM {{ ref('gold_fct_accounting_reconciliation') }}
),

with_lag AS (
    SELECT
        *,
        LAG(delta) OVER (PARTITION BY party ORDER BY month)                        AS previous_delta,
        CASE
            WHEN ABS(delta) > ABS(LAG(delta) OVER (PARTITION BY party ORDER BY month))
            THEN TRUE ELSE FALSE
        END                                                                         AS is_widening
    FROM base
),

islands AS (
    SELECT
        *,
        SUM(CASE WHEN NOT is_widening THEN 1 ELSE 0 END)
            OVER (PARTITION BY party ORDER BY month
                  ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)                AS island_grp
    FROM with_lag
)

SELECT
    party,
    month,
    finance_premium,
    accounting_premium,
    delta,
    previous_delta,
    ROUND(((delta - previous_delta))::numeric, 2)                                  AS delta_change,
    is_widening,
    CASE
        WHEN is_widening
        THEN ROW_NUMBER() OVER (PARTITION BY party, island_grp ORDER BY month)
        ELSE 0
    END                                                                            AS consecutive_widening,
    gap_pct,
    CASE
        WHEN gap_pct < 1 THEN '<1%'
        WHEN gap_pct < 5 THEN '1–5%'
        ELSE '>5%'
    END                                                                            AS gap_band,
    reconciliation_status,
    current_timestamp                                                              AS _created_at
FROM islands
ORDER BY party, month