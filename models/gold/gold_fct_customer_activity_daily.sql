{{
    config(
        materialized='incremental',
        unique_key=['user_id', 'activity_date'],
        incremental_strategy='delete+insert',
        on_schema_change='sync_all_columns',
        tags=['gold', 'kpi']
    )
}}

with customers as (

    select *
    from (values
        ('USR001', date '2025-01-15', date '2025-02-01', null,              9.99,  'liability'),
        ('USR002', date '2025-01-20', date '2025-02-01', date '2025-04-30', 14.99, 'liability'),
        ('USR003', date '2025-03-01', date '2025-03-15', date '2025-06-30', 7.50,  'household'),
        ('USR004', date '2025-02-10', date '2025-02-15', null,              12.00, 'household'),
        ('USR005', date '2025-01-05', date '2025-01-10', date '2025-03-31', 5.99,  'legal')
    ) t(user_id, acquisition_date, started_at, churned_at, monthly_premium, product_group)

),

date_spine as (

    select
        c.user_id,
        c.product_group,
        c.acquisition_date,
        c.started_at,
        c.churned_at,
        c.monthly_premium,
        d::date as activity_date

    from customers c,
        generate_series(
            c.started_at,
            coalesce(c.churned_at, current_date),
            interval '1 day'
        ) d

)

select
    activity_date,
    user_id,
    product_group,
    acquisition_date,
    started_at,
    churned_at,

    round(monthly_premium / extract(day from (date_trunc('month', activity_date) + interval '1 month - 1 day'))::numeric, 6) as daily_premium,

    monthly_premium,
    (activity_date - acquisition_date)                          as days_since_acquisition,
    to_char(activity_date, 'YYYY-MM')                           as activity_month,
    current_timestamp                                           as _loaded_at

from date_spine
