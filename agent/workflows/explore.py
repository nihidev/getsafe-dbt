import json
import os

from openai import OpenAI

from schemas import EXPLORE_SCHEMA as _SCHEMA

GOLD = os.environ.get("GOLD_SCHEMA", "public_gold")


def _gen_sql(question: str, openai_client: OpenAI) -> str:
    resp = openai_client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        messages=[
            {"role": "system", "content": f"You are a PostgreSQL expert. Write a single valid SELECT query to answer the question. Use schema prefix {GOLD}. Return ONLY raw SQL — no markdown, no explanation.\n\nCRITICAL SQL RULES:\n- The `month` column is VARCHAR in YYYY-MM format (e.g. '2025-06'). NEVER use EXTRACT() or DATE_PART() on it — it is not a date type.\n- To filter by year use: month LIKE '2025-%'\n- To filter by month range use: month >= '2025-01' AND month <= '2025-12'\n- To extract the year use: LEFT(month, 4)\n- To extract the month number use: RIGHT(month, 2)\n\n{_SCHEMA}"},
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
