"""
Data quality checks and table stats, extracted from main.py to break the
circular import: quality.py → main.py → quality.py.

Both main.py (tool execution) and workflows/quality.py import from here.
"""
import json
import re


def _run_checks(checks: dict, db) -> dict:
    results = {}
    for name, sql in checks.items():
        try:
            results[name] = db.query(sql, limit=200)
        except Exception as exc:
            results[name] = {"error": str(exc)}
    return results


def check_data_quality(table_name: str, db, gold_schema: str) -> str:
    s = gold_schema
    t = table_name
    full = f"{s}.{t}"

    if t == "gold_fct_monthly_premiums":
        checks = {
            "row_count": f"SELECT COUNT(*) AS total_rows FROM {full}",
            "null_check": f"""
                SELECT
                    COUNT(*) FILTER (WHERE party IS NULL)           AS null_party,
                    COUNT(*) FILTER (WHERE month IS NULL)           AS null_month,
                    COUNT(*) FILTER (WHERE premium IS NULL)         AS null_premium,
                    COUNT(*) FILTER (WHERE written_premium IS NULL) AS null_written_premium,
                    COUNT(*) FILTER (WHERE net_premium IS NULL)     AS null_net_premium,
                    COUNT(*) FILTER (WHERE earned_premium IS NULL)  AS null_earned_premium
                FROM {full}
            """,
            "uniqueness_check": f"""
                SELECT COUNT(*) AS duplicate_grain_rows
                FROM (
                    SELECT party, month FROM {full}
                    GROUP BY party, month HAVING COUNT(*) > 1
                ) dups
            """,
            "invalid_party_values": f"""
                SELECT party, COUNT(*) AS row_count
                FROM {full}
                WHERE party NOT IN ('berlinre','dronant','getland','liadigital')
                GROUP BY party
            """,
            "net_premium_sanity": f"""
                SELECT COUNT(*) AS rows_where_net_ne_written_minus_refunded
                FROM {full}
                WHERE ABS(net_premium - (written_premium - refunded_premium)) > 0.01
            """,
            "summary_by_party": f"""
                SELECT
                    party,
                    COUNT(*)                                         AS months,
                    MIN(month)                                       AS earliest_month,
                    MAX(month)                                       AS latest_month,
                    ROUND(SUM(written_premium)::numeric, 2)         AS total_written_eur,
                    ROUND(SUM(refunded_premium)::numeric, 2)        AS total_refunded_eur,
                    ROUND(SUM(net_premium)::numeric, 2)             AS total_net_eur,
                    SUM(transaction_count)                          AS total_transactions
                FROM {full}
                GROUP BY party ORDER BY total_written_eur DESC
            """,
        }

    elif t == "gold_fct_accounting_reconciliation":
        checks = {
            "row_count": f"SELECT COUNT(*) AS total_rows FROM {full}",
            "null_check": f"""
                SELECT
                    COUNT(*) FILTER (WHERE party IS NULL)                 AS null_party,
                    COUNT(*) FILTER (WHERE month IS NULL)                 AS null_month,
                    COUNT(*) FILTER (WHERE accounting_premium IS NULL)    AS null_accounting_premium,
                    COUNT(*) FILTER (WHERE finance_premium IS NULL)       AS null_finance_premium,
                    COUNT(*) FILTER (WHERE reconciliation_status IS NULL) AS null_status
                FROM {full}
            """,
            "uniqueness_check": f"""
                SELECT COUNT(*) AS duplicate_grain_rows
                FROM (
                    SELECT party, month FROM {full}
                    GROUP BY party, month HAVING COUNT(*) > 1
                ) dups
            """,
            "invalid_status_values": f"""
                SELECT reconciliation_status, COUNT(*) AS row_count
                FROM {full}
                WHERE reconciliation_status NOT IN ('MATCH','NEAR_MATCH','DISCREPANCY')
                GROUP BY reconciliation_status
            """,
            "status_distribution": f"""
                SELECT
                    reconciliation_status,
                    COUNT(*)                                    AS occurrences,
                    ROUND(AVG(ABS(delta))::numeric, 2)         AS avg_abs_delta_eur,
                    ROUND(MAX(ABS(delta))::numeric, 2)         AS max_abs_delta_eur,
                    ROUND(AVG(delta_pct)::numeric, 4)          AS avg_delta_pct
                FROM {full}
                GROUP BY reconciliation_status ORDER BY occurrences DESC
            """,
            "top_discrepancies": f"""
                SELECT party, month, finance_premium, accounting_premium,
                       delta, delta_pct, reconciliation_status
                FROM {full}
                ORDER BY ABS(delta) DESC LIMIT 5
            """,
        }

    elif t == "gold_fct_customer_activity_daily":
        checks = {
            "row_count": f"SELECT COUNT(*) AS total_rows FROM {full}",
            "null_check": f"""
                SELECT
                    COUNT(*) FILTER (WHERE user_id IS NULL)        AS null_user_id,
                    COUNT(*) FILTER (WHERE activity_date IS NULL)  AS null_activity_date,
                    COUNT(*) FILTER (WHERE product_group IS NULL)  AS null_product_group,
                    COUNT(*) FILTER (WHERE daily_premium IS NULL)  AS null_daily_premium
                FROM {full}
            """,
            "uniqueness_check": f"""
                SELECT COUNT(*) AS duplicate_grain_rows
                FROM (
                    SELECT user_id, activity_date FROM {full}
                    GROUP BY user_id, activity_date HAVING COUNT(*) > 1
                ) dups
            """,
            "date_range": f"""
                SELECT MIN(activity_date) AS earliest, MAX(activity_date) AS latest,
                       COUNT(DISTINCT activity_date) AS distinct_dates
                FROM {full}
            """,
            "customer_summary": f"""
                SELECT
                    user_id,
                    product_group,
                    MIN(activity_date)                              AS first_active,
                    MAX(activity_date)                             AS last_active,
                    COUNT(*)                                       AS active_days,
                    ROUND(SUM(daily_premium)::numeric, 2)         AS total_earned_eur,
                    CASE WHEN MAX(churned_at) IS NOT NULL
                         THEN 'churned' ELSE 'active' END         AS status
                FROM {full}
                GROUP BY user_id, product_group ORDER BY total_earned_eur DESC
            """,
            "product_group_breakdown": f"""
                SELECT
                    product_group,
                    COUNT(DISTINCT user_id)                        AS customers,
                    ROUND(AVG(monthly_premium)::numeric, 2)       AS avg_monthly_premium_eur,
                    COUNT(*) FILTER (WHERE churned_at IS NOT NULL) AS churned_user_days
                FROM {full}
                GROUP BY product_group ORDER BY customers DESC
            """,
        }
    else:
        return json.dumps({"error": f"Unknown table: {table_name}"})

    return json.dumps(_run_checks(checks, db), default=str)


def get_table_stats(table_name: str, schema_name: str, db) -> str:
    full = f"{schema_name}.{table_name}"

    # Parameterised query — no string interpolation of user/LLM-supplied values
    cols = db.query_safe(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s "
        "ORDER BY ordinal_position",
        (schema_name, table_name),
        limit=200,
    )

    if "error" in cols:
        return json.dumps(cols)

    columns = cols.get("rows", [])
    if not columns:
        return json.dumps({"error": f"Table {full} not found or has no columns"})

    # Strip non-alphanumeric chars from column names before embedding in SQL
    safe_cols = [re.sub(r"[^a-zA-Z0-9_]", "", c["column_name"]) for c in columns]
    null_exprs = ", ".join(
        f"COUNT(*) FILTER (WHERE {col} IS NULL) AS null_{col}"
        for col in safe_cols
        if col
    )

    row_count = db.query(f"SELECT COUNT(*) AS total_rows FROM {full}", limit=1)
    null_counts = db.query(f"SELECT {null_exprs} FROM {full}", limit=1)

    return json.dumps(
        {"table": full, "columns": columns, "row_count": row_count, "null_counts": null_counts},
        default=str,
    )
