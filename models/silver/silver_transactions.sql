{{
    config(
        materialized='table',
        tags=['silver']
    )
}}

with source as (
    select * from {{ ref('bronze_raw_transactions') }}
),

parsed as (
    select
        transaction_id,

        case
            when created_at ~ '^\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2}$'
            then to_timestamp(created_at, 'FMMM/FMDD/YYYY FMHH24:MI:SS')
            else null
        end                                                                 as created_at_ts,
        case
            when created_at ~ '^\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2}$'
            then to_timestamp(created_at, 'FMMM/FMDD/YYYY FMHH24:MI:SS')::date
            else null
        end                                                                 as transaction_date,
        case
            when created_at ~ '^\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2}$'
            then to_char(to_timestamp(created_at, 'FMMM/FMDD/YYYY FMHH24:MI:SS'), 'YYYY-MM')
            else null
        end                                                                 as transaction_month,

        premium_amount,
        premium_currency,
        charged_party,
        status                                                              as status_raw,
        created_at                                                          as created_at_raw,
        _source_file,
        _ingested_at

    from source
),

normalized as (
    select
        *,

        case when status_raw = 'process' then 'processed' else status_raw end as status,
        (status_raw = 'process')                                               as _status_normalized

    from parsed
),

with_dq as (
    select
        *,
        array_to_string(
            array_remove(
                array[
                    case when created_at_ts  is null then 'unparseable_timestamp' else null end,
                    case when premium_amount is null then 'unparseable_premium'   else null end,
                    case when premium_amount < 0     then 'negative_premium'      else null end,
                    case when charged_party  is null then 'missing_party'         else null end
                ],
                null
            ),
            ','
        )                                   as _dq_flags,

        (
            created_at_ts  is not null
            and premium_amount is not null
            and premium_amount >= 0
            and charged_party  is not null
        )                                   as _is_clean

    from normalized
)

select
    transaction_id,
    created_at_ts,
    transaction_date,
    transaction_month,
    premium_amount,
    premium_currency,
    charged_party                           as party,
    status,
    status_raw,
    _status_normalized,
    _dq_flags,
    _is_clean,
    _source_file,
    _ingested_at                            as _bronze_ingested_at,
    current_timestamp                       as _silver_transformed_at

from with_dq
