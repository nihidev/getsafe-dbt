{{ config(materialized='table', tags=['gold']) }}

WITH customer_activity AS (
    SELECT
        user_id,
        acquisition_date,
        activity_date,
        EXTRACT(YEAR FROM acquisition_date) AS acquisition_year,
        EXTRACT(MONTH FROM acquisition_date) AS acquisition_month,
        EXTRACT(YEAR FROM activity_date) AS activity_year,
        EXTRACT(MONTH FROM activity_date) AS activity_month,
        daily_premium
    FROM {{ ref('gold_fct_customer_activity_daily') }}
),

cohort_analysis AS (
    SELECT
        acquisition_year,
        acquisition_month,
        activity_year,
        activity_month,
        COUNT(DISTINCT user_id) AS active_customers,
        SUM(daily_premium) AS total_premium
    FROM customer_activity
    GROUP BY
        acquisition_year,
        acquisition_month,
        activity_year,
        activity_month
),

retention_triangle AS (
    SELECT
        acquisition_year,
        acquisition_month,
        activity_year,
        activity_month,
        active_customers,
        ROUND(
            (active_customers::numeric / NULLIF(
                FIRST_VALUE(active_customers) OVER (PARTITION BY acquisition_year, acquisition_month ORDER BY activity_year, activity_month),
                0
            )) * 100, 2
        ) AS retention_rate
    FROM cohort_analysis
),

cumulative_premium AS (
    SELECT
        acquisition_year,
        acquisition_month,
        activity_year,
        activity_month,
        SUM(total_premium) OVER (PARTITION BY acquisition_year, acquisition_month ORDER BY activity_year, activity_month) AS cumulative_premium
    FROM cohort_analysis
),

final AS (
    SELECT
        r.acquisition_year,
        r.acquisition_month,
        r.activity_year,
        r.activity_month,
        r.retention_rate,
        ROUND(cp.cumulative_premium / NULLIF(
            FIRST_VALUE(active_customers) OVER (PARTITION BY r.acquisition_year, r.acquisition_month ORDER BY r.activity_year, r.activity_month),
            0
        ), 2) AS avg_cumulative_premium_per_customer
    FROM retention_triangle r
    JOIN cumulative_premium cp
    ON r.acquisition_year = cp.acquisition_year
    AND r.acquisition_month = cp.acquisition_month
    AND r.activity_year = cp.activity_year
    AND r.activity_month = cp.activity_month
),

steepest_drop_off AS (
    SELECT
        acquisition_year,
        acquisition_month,
        MIN(retention_rate) AS min_retention_rate
    FROM final
    WHERE acquisition_year = 2024 AND acquisition_month IN (1, 2, 3)
    GROUP BY acquisition_year, acquisition_month
    ORDER BY min_retention_rate
    LIMIT 1
),

highest_avg_cumulative_premium AS (
    SELECT
        acquisition_year,
        acquisition_month,
        MAX(avg_cumulative_premium_per_customer) AS max_avg_cumulative_premium
    FROM final
    WHERE acquisition_year = 2024 AND acquisition_month IN (1, 2, 3) AND activity_month <= 6
    GROUP BY acquisition_year, acquisition_month
    ORDER BY max_avg_cumulative_premium DESC
    LIMIT 1
)

SELECT
    f.acquisition_year,
    f.acquisition_month,
    f.activity_year,
    f.activity_month,
    f.retention_rate,
    f.avg_cumulative_premium_per_customer,
    CASE WHEN f.acquisition_year = sd.acquisition_year AND f.acquisition_month = sd.acquisition_month THEN 'Steepest Drop-off' ELSE NULL END AS steepest_drop_off_cohort,
    CASE WHEN f.acquisition_year = ha.acquisition_year AND f.acquisition_month = ha.acquisition_month THEN 'Highest Avg Cumulative Premium' ELSE NULL END AS highest_avg_cumulative_premium_cohort,
    NOW() AS _created_at
FROM final f
LEFT JOIN steepest_drop_off sd
ON f.acquisition_year = sd.acquisition_year AND f.acquisition_month = sd.acquisition_month
LEFT JOIN highest_avg_cumulative_premium ha
ON f.acquisition_year = ha.acquisition_year AND f.acquisition_month = ha.acquisition_month
WHERE f.acquisition_year = 2024 AND f.acquisition_month IN (1, 2, 3)
ORDER BY f.acquisition_year, f.acquisition_month, f.activity_year, f.activity_month;