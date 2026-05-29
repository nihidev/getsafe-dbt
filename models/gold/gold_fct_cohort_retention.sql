{{ config(materialized='table', tags=['gold']) }}

WITH cte_user_monthly_activity AS (
    SELECT
        DISTINCT user_id,
        product_group,
        DATE_TRUNC('month', activity_date) AS activity_month
    FROM
        {{ ref('gold_fct_customer_activity_daily') }}
),

cte_cohort_size AS (
    SELECT
        DATE_TRUNC('month', acquisition_date) AS cohort_month,
        product_group,
        COUNT(DISTINCT user_id) AS cohort_size
    FROM
        {{ ref('gold_fct_customer_activity_daily') }}
    WHERE
        DATE_TRUNC('month', acquisition_date) = DATE_TRUNC('month', activity_date)
    GROUP BY
        cohort_month,
        product_group
),

cte_active_customers AS (
    SELECT
        DATE_TRUNC('month', cad.acquisition_date) AS cohort_month,
        cad.product_group,
        DATE_PART('month', AGE(uma.activity_month, DATE_TRUNC('month', cad.acquisition_date)))::INTEGER AS months_since_acquisition,
        COUNT(DISTINCT uma.user_id) AS active_customers
    FROM
        cte_user_monthly_activity uma
    JOIN
        {{ ref('gold_fct_customer_activity_daily') }} AS cad
    ON
        uma.user_id = cad.user_id
        AND uma.activity_month = DATE_TRUNC('month', cad.activity_date)
    GROUP BY
        cohort_month,
        cad.product_group,
        months_since_acquisition
),

cte_cohort_retention AS (
    SELECT
        ac.cohort_month,
        ac.product_group,
        ac.months_since_acquisition,
        cs.cohort_size,
        ac.active_customers,
        ROUND((100.0 * ac.active_customers / NULLIF(cs.cohort_size, 0))::numeric, 1) AS retention_rate
    FROM
        cte_active_customers ac
    INNER JOIN
        cte_cohort_size cs
    ON
        ac.cohort_month = cs.cohort_month
        AND ac.product_group = cs.product_group
)

SELECT
    cohort_month,
    product_group,
    months_since_acquisition,
    cohort_size,
    active_customers,
    retention_rate,
    current_timestamp AS _created_at
FROM
    cte_cohort_retention