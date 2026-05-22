import os
import re

GOLD = os.environ.get("GOLD_SCHEMA", "public_gold")
METABASE_PUBLIC_URL = os.environ.get("METABASE_PUBLIC_URL", "http://localhost:12345")

# Whitelist of allowed filter keys per table
_ALLOWED_FILTERS: dict[str, set] = {
    "gold_fct_monthly_premiums":          {"party", "month"},
    "gold_fct_accounting_reconciliation": {"party", "month", "reconciliation_status"},
    "gold_fct_customer_activity_daily":   {"user_id", "product_group", "activity_date"},
}

# Only alphanumeric, hyphens, underscores — no quotes, semicolons, or spaces
_SAFE_VALUE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def _safe_where(table: str, filters) -> str:
    if not filters:
        return ""
    allowed = _ALLOWED_FILTERS.get(table, set())
    clauses = []
    for k, v in filters.items():
        if k not in allowed:
            continue
        v = str(v)
        if not _SAFE_VALUE.match(v):
            continue
        # month is VARCHAR YYYY-MM — a bare year must become a LIKE filter
        if k == "month" and re.match(r"^\d{4}$", v):
            clauses.append(f"month LIKE '{v}-%'")
        else:
            clauses.append(f"{k} = '{v}'")
    return "WHERE " + " AND ".join(clauses) if clauses else ""


def _build_sql(intent: dict) -> str:
    table    = intent.get("table") or "gold_fct_monthly_premiums"
    where    = _safe_where(table, intent.get("filters"))
    group_by = intent.get("group_by", "party_month")

    if "monthly_premiums" in table:
        if group_by == "party":
            # Compare parties side-by-side, aggregated across all months
            return f"""
SELECT party,
       ROUND(SUM(written_premium)::numeric, 2)  AS written_premium,
       ROUND(SUM(net_premium)::numeric, 2)       AS net_premium,
       ROUND(SUM(refunded_premium)::numeric, 2)  AS refunded_premium,
       SUM(transaction_count)                    AS transaction_count
FROM {GOLD}.gold_fct_monthly_premiums
{where}
GROUP BY party
ORDER BY written_premium DESC
""".strip()
        elif group_by == "month":
            # Time trend across all parties
            return f"""
SELECT month,
       ROUND(SUM(written_premium)::numeric, 2)  AS written_premium,
       ROUND(SUM(net_premium)::numeric, 2)       AS net_premium,
       ROUND(SUM(refunded_premium)::numeric, 2)  AS refunded_premium
FROM {GOLD}.gold_fct_monthly_premiums
{where}
GROUP BY month
ORDER BY month
""".strip()
        else:
            # Full breakdown: party × month
            return f"""
SELECT party, month,
       ROUND(SUM(written_premium)::numeric, 2)  AS written_premium,
       ROUND(SUM(net_premium)::numeric, 2)       AS net_premium,
       ROUND(SUM(refunded_premium)::numeric, 2)  AS refunded_premium
FROM {GOLD}.gold_fct_monthly_premiums
{where}
GROUP BY party, month
ORDER BY party, month
""".strip()

    if "reconciliation" in table:
        if group_by == "party":
            return f"""
SELECT party,
       ROUND(SUM(finance_premium)::numeric, 2)    AS finance_premium,
       ROUND(SUM(accounting_premium)::numeric, 2) AS accounting_premium,
       ROUND(SUM(delta)::numeric, 2)              AS total_delta,
       ROUND(AVG(delta_pct)::numeric, 2)          AS avg_delta_pct
FROM {GOLD}.gold_fct_accounting_reconciliation
{where}
GROUP BY party
ORDER BY party
""".strip()
        else:
            return f"""
SELECT party, month,
       ROUND(finance_premium::numeric, 2)    AS finance_premium,
       ROUND(accounting_premium::numeric, 2) AS accounting_premium,
       ROUND(delta::numeric, 2)              AS delta,
       ROUND(delta_pct::numeric, 2)          AS delta_pct,
       reconciliation_status
FROM {GOLD}.gold_fct_accounting_reconciliation
{where}
ORDER BY party, month
""".strip()

    if "customer" in table or "daily" in table:
        return f"""
SELECT product_group,
       COUNT(DISTINCT user_id)                 AS customers,
       ROUND(SUM(daily_premium)::numeric, 2)   AS total_daily_premium,
       ROUND(AVG(monthly_premium)::numeric, 2) AS avg_monthly_premium
FROM {GOLD}.gold_fct_customer_activity_daily
{where}
GROUP BY product_group
ORDER BY total_daily_premium DESC
""".strip()

    return f"SELECT * FROM {GOLD}.{table} {where} LIMIT 100"


def run(intent: dict, db, metabase) -> dict:
    title = intent.get("metric") or "Auto Dashboard"
    chart_type = intent.get("chart_type") or "bar"
    sql = _build_sql(intent)

    result = db.query(sql, limit=200)
    if "error" in result:
        return {"success": False, "error": result["error"]}

    db_id = metabase.get_database_id()
    card = metabase.create_question(name=title, sql=sql, display=chart_type, database_id=db_id)
    dash = metabase.create_dashboard(name=title, description="Auto-generated from Linear ticket")
    metabase.add_card_to_dashboard(dashboard_id=dash["id"], card_id=card["id"])

    return {
        "success": True,
        "card_id": card["id"],
        "dashboard_id": dash["id"],
        "dashboard_url": f"{METABASE_PUBLIC_URL}/dashboard/{dash['id']}",
        "question_url": f"{METABASE_PUBLIC_URL}/question/{card['id']}",
        "sql": sql,
        "row_count": result.get("row_count", 0),
    }
