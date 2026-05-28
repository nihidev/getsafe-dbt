WITH user_monthly AS (
    SELECT
        user_id,
        product_group,
        DATE_TRUNC('month', activity_date) AS month
    FROM
        {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY
        user_id, product_group, DATE_TRUNC('month', activity_date)
),

churned_user_list AS (
    SELECT
        prev.user_id,
        prev.product_group,
        prev.month AS last_active_month
    FROM
        user_monthly prev
    LEFT JOIN
        user_monthly curr
    ON
        prev.user_id = curr.user_id
        AND prev.product_group = curr.product_group
        AND prev.month + INTERVAL '1 month' = curr.month
    WHERE
        curr.user_id IS NULL
),

monthly_activity AS (
    SELECT
        user_id,
        DATE_TRUNC('month', activity_date) AS month,
        SUM(daily_premium) AS monthly_premium,
        CASE
            WHEN DATE_TRUNC('month', activity_date) = DATE_TRUNC('month', acquisition_date) THEN 'new_business'
            WHEN LAG(DATE_TRUNC('month', activity_date)) OVER (PARTITION BY user_id ORDER BY DATE_TRUNC('month', activity_date)) IS NOT NULL THEN 'renewal'
            ELSE NULL
        END AS transaction_type
    FROM
        {{ ref('gold_fct_customer_activity_daily') }}
    GROUP BY
        user_id, DATE_TRUNC('month', activity_date), acquisition_date
),

lapsed_premium AS (
    SELECT
        l.user_id,
        l.last_active_month,
        SUM(m.monthly_premium) AS lapsed_premium
    FROM
        churned_user_list l
    INNER JOIN
        monthly_activity m
    ON
        l.user_id = m.user_id
        AND l.last_active_month = m.month
    GROUP BY
        l.user_id, l.last_active_month
),

party_monthly_aggregation AS (
    SELECT
        ma.user_id,
        ma.month,
        SUM(CASE WHEN ma.transaction_type = 'new_business' THEN ma.monthly_premium ELSE 0 END) AS new_business_premium,
        SUM(CASE WHEN ma.transaction_type = 'renewal' THEN ma.monthly_premium ELSE 0 END) AS renewal_premium,
        COALESCE(lp.lapsed_premium, 0) AS lapsed_premium
    FROM
        monthly_activity ma
    LEFT JOIN
        lapsed_premium lp
    ON
        ma.user_id = lp.user_id
        AND ma.month = lp.last_active_month + INTERVAL '1 month'
    GROUP BY
        ma.user_id, ma.month
)

SELECT
    gmp.party,
    p.month,
    SUM(p.new_business_premium) AS new_business_premium,
    SUM(p.renewal_premium) AS renewal_premium,
    SUM(p.lapsed_premium) AS lapsed_premium,
    SUM(p.new_business_premium + p.renewal_premium - p.lapsed_premium) AS net_written_premium,
    ROUND(SUM(p.lapsed_premium) / NULLIF(SUM(p.new_business_premium), 0), 2) AS lapse_to_new_business_ratio,
    current_timestamp AS _created_at
FROM
    party_monthly_aggregation p
JOIN
    {{ ref('gold_fct_monthly_premiums') }} gmp
ON
    p.user_id = gmp.party
    AND p.month::text = gmp.month
GROUP BY
    gmp.party, p.month