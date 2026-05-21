import asyncio
import json
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel

from db_client import DatabaseClient
from github_client import GitHubClient
from linear_client import LinearClient
from metabase_client import MetabaseClient
from schema_context import SCHEMA_CONTEXT
from tools import TOOLS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="GetSafe Analytics Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

metabase = MetabaseClient(
    base_url=os.environ.get("METABASE_URL", "http://host.docker.internal:12345"),
    api_key=os.environ["METABASE_API_KEY"],
)

db = DatabaseClient(
    host=os.environ["SUPABASE_HOST"],
    port=int(os.environ.get("SUPABASE_PORT", "5432")),
    dbname=os.environ.get("SUPABASE_DB", "postgres"),
    user=os.environ["SUPABASE_USER"],
    password=os.environ["SUPABASE_PASSWORD"],
)

linear = LinearClient(
    api_key=os.environ.get("LINEAR_API_KEY", ""),
    team_id=os.environ.get("LINEAR_TEAM_ID", "5a12d787-f028-47d5-91bf-c7b9c45a4ecc"),
)

github = GitHubClient(
    pat=os.environ.get("GITHUB_PAT", ""),
    repo=os.environ.get("GITHUB_REPO", "nihidev/getsafe-dbt"),
)

GOLD_SCHEMA = os.environ.get("GOLD_SCHEMA", "public_gold")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

SYSTEM_PROMPT = f"""You are a data analytics assistant for GetSafe, an InsurTech company.
You help business users explore data and create visualizations in Metabase without writing SQL.

{SCHEMA_CONTEXT}

The gold schema name in Supabase is: {GOLD_SCHEMA}
Always prefix table names: {GOLD_SCHEMA}.gold_fct_monthly_premiums

When the user asks for a chart or analysis, follow this sequence:
1. run_sql_query — validate the data and confirm it returns what the user expects
2. create_metabase_question — save it with the right visualization type
3. Optionally create a dashboard and add the question to it
4. Tell the user what was created and give the question/dashboard ID

Visualization guide:
  time series → line or area
  category comparisons → bar
  proportions/shares → pie
  single KPI number → scalar
  raw data exploration → table

You also have data quality tools:
- check_data_quality(table_name) — runs null checks, uniqueness, accepted values, and business summaries.
  Use this when the user asks about data quality, dbt test results, or wants to audit a table.
- get_table_stats(table_name, schema_name) — generic column list + null counts for any table across
  bronze, silver, or gold schemas. Use schema public_bronze, public_silver, or public_gold.
"""


# ── request/response models ────────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


class ChatResponse(BaseModel):
    response: str
    actions_taken: list[str]


# ── quality check helpers ─────────────────────────────────────────────────────

def _run_checks(checks: dict[str, str]) -> dict:
    results = {}
    for check_name, sql in checks.items():
        try:
            results[check_name] = db.query(sql, limit=200)
        except Exception as exc:
            results[check_name] = {"error": str(exc)}
    return results


def _check_data_quality(table_name: str) -> str:
    s = GOLD_SCHEMA
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
                    COUNT(*) FILTER (WHERE party IS NULL)                AS null_party,
                    COUNT(*) FILTER (WHERE month IS NULL)                AS null_month,
                    COUNT(*) FILTER (WHERE accounting_premium IS NULL)   AS null_accounting_premium,
                    COUNT(*) FILTER (WHERE finance_premium IS NULL)      AS null_finance_premium,
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

    return json.dumps(_run_checks(checks), default=str)


def _get_table_stats(table_name: str, schema_name: str) -> str:
    full = f"{schema_name}.{table_name}"

    cols = db.query(
        f"""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = '{schema_name}' AND table_name = '{table_name}'
        ORDER BY ordinal_position
        """,
        limit=200,
    )

    if "error" in cols:
        return json.dumps(cols)

    columns = cols.get("rows", [])
    if not columns:
        return json.dumps({"error": f"Table {full} not found or has no columns"})

    null_exprs = ", ".join(
        f"COUNT(*) FILTER (WHERE {c['column_name']} IS NULL) AS null_{c['column_name']}"
        for c in columns
    )

    row_count = db.query(f"SELECT COUNT(*) AS total_rows FROM {full}", limit=1)
    null_counts = db.query(f"SELECT {null_exprs} FROM {full}", limit=1)

    return json.dumps(
        {
            "table": full,
            "columns": columns,
            "row_count": row_count,
            "null_counts": null_counts,
        },
        default=str,
    )


# ── tool execution ─────────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict) -> str:
    try:
        if name == "run_sql_query":
            result = db.query(args["sql"], limit=args.get("limit", 100))
            return json.dumps(result, default=str)

        elif name == "create_metabase_question":
            db_id = metabase.get_database_id()
            card = metabase.create_question(
                name=args["name"],
                sql=args["sql"],
                display=args["display"],
                database_id=db_id,
                collection_id=args.get("collection_id"),
            )
            return json.dumps({
                "card_id": card["id"],
                "name": card["name"],
                "url": f"/question/{card['id']}",
            })

        elif name == "create_metabase_dashboard":
            dash = metabase.create_dashboard(
                name=args["name"],
                description=args.get("description", ""),
            )
            return json.dumps({
                "dashboard_id": dash["id"],
                "name": dash["name"],
                "url": f"/dashboard/{dash['id']}",
            })

        elif name == "add_question_to_dashboard":
            result = metabase.add_card_to_dashboard(
                dashboard_id=args["dashboard_id"],
                card_id=args["card_id"],
                row=args.get("row", 0),
                col=args.get("col", 0),
                size_x=args.get("size_x", 12),
                size_y=args.get("size_y", 8),
            )
            return json.dumps({"success": True, "dashcard_id": result.get("id")})

        elif name == "list_metabase_questions":
            cards = metabase.list_questions()
            return json.dumps([{"id": c["id"], "name": c["name"]} for c in cards[:20]])

        elif name == "list_metabase_dashboards":
            dashes = metabase.list_dashboards()
            return json.dumps([{"id": d["id"], "name": d["name"]} for d in dashes[:20]])

        elif name == "check_data_quality":
            return _check_data_quality(args["table_name"])

        elif name == "get_table_stats":
            return _get_table_stats(
                args["table_name"],
                args.get("schema_name", GOLD_SCHEMA),
            )

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── agent loop ────────────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": m.role, "content": m.content} for m in request.messages]

    actions_taken: list[str] = []

    for _ in range(10):
        completion = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        msg = completion.choices[0].message

        if not msg.tool_calls:
            return ChatResponse(response=msg.content or "", actions_taken=actions_taken)

        messages.append(msg)

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            result = execute_tool(fn_name, fn_args)

            label = f"{fn_name}({json.dumps(fn_args)[:100]})"
            actions_taken.append(label)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    return ChatResponse(
        response="Reached maximum tool-call iterations without a final answer.",
        actions_taken=actions_taken,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── linear pipeline endpoints ─────────────────────────────────────────────────

class TicketRequest(BaseModel):
    ticket_identifier: str  # e.g. "GET-12"


@app.post("/process-ticket")
async def process_ticket_endpoint(req: TicketRequest):
    """Manually trigger processing of a specific Linear ticket by identifier."""
    from polling import process_ticket

    ticket = linear.get_ticket(req.ticket_identifier)
    if not ticket:
        return {"success": False, "error": f"Ticket {req.ticket_identifier} not found"}

    await process_ticket(ticket, linear, db, metabase, github, openai_client)
    return {"success": True, "ticket": req.ticket_identifier}


@app.get("/poll-now")
async def poll_now():
    """Manually trigger one polling cycle — useful for testing."""
    from polling import process_ticket

    tickets = linear.get_pending_tickets()
    if not tickets:
        return {"processed": 0, "message": "No pending analytics-request tickets found"}

    for t in tickets:
        await process_ticket(t, linear, db, metabase, github, openai_client)

    return {"processed": len(tickets)}


class PostMergeRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    model_name: str       # e.g. "gold_fct_premium_concentration_hhi"
    ticket_identifier: str  # e.g. "GET-3"


@app.post("/post-merge")
async def post_merge_endpoint(req: PostMergeRequest):
    """
    Trigger the post-merge workflow manually (or from GitHub Actions).
    Looks up the Linear ticket, checks the table exists, builds Metabase dashboard,
    and marks the ticket Done.
    """
    import workflows.post_merge as post_merge_wf

    ticket = linear.get_ticket(req.ticket_identifier)
    if not ticket:
        return {"success": False, "error": f"Ticket {req.ticket_identifier} not found"}

    result = post_merge_wf.run(
        model_name=req.model_name,
        ticket_identifier=req.ticket_identifier,
        issue_id=ticket["id"],
        label_ids=ticket.get("labelIds") or [],
        db=db,
        metabase=metabase,
        linear=linear,
    )
    return {"success": True, **result}


# ── startup: begin polling loop ───────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    if os.environ.get("ENABLE_POLLING", "true").lower() == "true":
        interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "120"))
        from polling import start_polling
        asyncio.create_task(
            start_polling(interval, linear, db, metabase, github, openai_client)
        )
