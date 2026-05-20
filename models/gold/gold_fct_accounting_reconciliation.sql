{{
    config(
        materialized='table',
        tags=['gold', 'finance', 'reconciliation']
    )
}}

with accounting as (

    select party, month, accounting_premium
    from {{ ref('accounting_closing') }}

),

finance as (

    select
        party,
        month,
        written_premium,
        net_premium,
        refunded_premium,
        transaction_count

    from {{ ref('gold_fct_monthly_premiums') }}

),

reconciled as (

    select
        a.party,
        a.month,
        a.accounting_premium,
        coalesce(f.written_premium, 0.0)                        as finance_premium,
        coalesce(f.net_premium, 0.0)                            as net_premium,
        coalesce(f.refunded_premium, 0.0)                       as refunded_premium,
        coalesce(f.transaction_count, 0)                        as transaction_count,

        round((coalesce(f.written_premium, 0.0) - a.accounting_premium)::numeric, 2) as delta,

        round(
            (abs(coalesce(f.written_premium, 0.0) - a.accounting_premium)
            / nullif(a.accounting_premium, 0) * 100)::numeric,
            4
        )                                                       as delta_pct,

        round((coalesce(f.net_premium, 0.0) - a.accounting_premium)::numeric, 2) as net_delta,

        case
            when abs(coalesce(f.written_premium, 0.0) - a.accounting_premium) < 0.01
                then 'MATCH'
            when abs(coalesce(f.written_premium, 0.0) - a.accounting_premium)
                / nullif(a.accounting_premium, 0) < 0.01
                then 'NEAR_MATCH'
            else 'DISCREPANCY'
        end                                                     as reconciliation_status,

        abs(coalesce(f.written_premium, 0.0) - a.accounting_premium) < 0.01 as is_reconciled

    from accounting a
    left join finance f
        on a.party = f.party
        and a.month = f.month

)

select
    party,
    month,
    accounting_premium,
    finance_premium,
    net_premium,
    refunded_premium,
    net_delta,
    transaction_count,
    delta,
    delta_pct,
    reconciliation_status,
    is_reconciled,
    current_timestamp as _reconciled_at

from reconciled
order by party, month
