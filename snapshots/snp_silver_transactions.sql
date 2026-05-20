{% snapshot snp_silver_transactions %}

{{
    config(
        target_schema='snapshots',
        unique_key='transaction_id',
        strategy='check',
        check_cols=['status', 'premium_amount'],
        invalidate_hard_deletes=True
    )
}}

select
    transaction_id,
    transaction_date,
    transaction_month,
    premium_amount,
    premium_currency,
    party,
    status,
    status_raw,
    _status_normalized,
    _dq_flags,
    _is_clean,
    _bronze_ingested_at,
    _silver_transformed_at

from {{ ref('silver_transactions') }}

{% endsnapshot %}
