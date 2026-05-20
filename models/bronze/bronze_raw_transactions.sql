{{
    config(
        materialized='table',
        tags=['bronze']
    )
}}

select
    transaction_id,
    created_at,
    premium_amount::double precision,
    premium_currency,
    charged_party,
    status,
    'raw_transactions.csv'  as _source_file,
    current_timestamp       as _ingested_at

from {{ ref('raw_transactions') }}
