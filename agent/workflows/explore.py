import json
import os

from openai import OpenAI

GOLD = os.environ.get("GOLD_SCHEMA", "public_gold")

_SCHEMA = f"""Gold layer tables (schema: {GOLD}):
- gold_fct_monthly_premiums       — party, month, written_premium, net_premium, refunded_premium, earned_premium, transaction_count
- gold_fct_accounting_reconciliation — party, month, accounting_premium, finance_premium, delta, delta_pct, reconciliation_status
- gold_fct_customer_activity_daily  — user_id, activity_date, product_group, daily_premium, monthly_premium, churned_at, days_since_acquisition"""


def _gen_sql(question: str, openai_client: OpenAI) -> str:
    resp = openai_client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        messages=[
            {"role": "system", "content": f"You are a PostgreSQL expert. Write a single valid SELECT query to answer the question. Use schema prefix {GOLD}. Return ONLY raw SQL — no markdown, no explanation.\n\n{_SCHEMA}"},
            {"role": "user",   "content": question},
        ],
        temperature=0,
    )
    sql = resp.choices[0].message.content.strip()
    return sql.replace("```sql", "").replace("```", "").strip()


def _summarise(question: str, sql: str, results: dict, openai_client: OpenAI) -> str:
    preview = json.dumps(results.get("rows", [])[:10], default=str, indent=2)
    resp = openai_client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        messages=[
            {"role": "system", "content": "You are a senior data analyst. Answer the question in plain English. Be concise, cite key numbers, and flag any data caveats."},
            {"role": "user",   "content": f"Question: {question}\n\nSQL:\n{sql}\n\nResults ({results.get('row_count', 0)} rows):\n{preview}"},
        ],
    )
    return resp.choices[0].message.content.strip()


def run(intent: dict, db, openai_client: OpenAI) -> dict:
    question = intent.get("metric") or "Summarise the available data"

    sql = _gen_sql(question, openai_client)
    results = db.query(sql, limit=50)

    if "error" in results:
        return {"success": False, "error": results["error"], "sql": sql}

    summary = _summarise(question, sql, results, openai_client)

    return {
        "success": True,
        "sql": sql,
        "row_count": results.get("row_count", 0),
        "summary": summary,
        "sample_rows": results.get("rows", [])[:5],
    }
