import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel

from checks import check_data_quality, get_table_stats
from db_client import DatabaseClient
from github_client import GitHubClient
from linear_client import LinearClient
from metabase_client import MetabaseClient
from polling import check_merged_prs, init_tracked_prs, process_ticket
from schemas import SCHEMA_CONTEXT
from tools import TOOLS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ── service clients ───────────────────────────────────────────────────────────

openai_client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    timeout=60.0,
)

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


# ── lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.ensure_tracked_prs_table()
    init_tracked_prs(db)
    yield


app = FastAPI(title="GetSafe Analytics Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── request / response models ─────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


class ChatResponse(BaseModel):
    response: str
    actions_taken: list[str]


# ── tool execution ────────────────────────────────────────────────────────────

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
            return check_data_quality(args["table_name"], db, GOLD_SCHEMA)

        elif name == "get_table_stats":
            return get_table_stats(
                args["table_name"],
                args.get("schema_name", GOLD_SCHEMA),
                db,
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

            actions_taken.append(f"{fn_name}({json.dumps(fn_args)[:100]})")

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
    """Process a specific Linear ticket by identifier. Called by N8N on ticket creation."""
    ticket = linear.get_ticket(req.ticket_identifier)
    if not ticket:
        return {"success": False, "error": f"Ticket {req.ticket_identifier} not found"}

    await process_ticket(ticket, linear, db, metabase, github, openai_client)
    return {"success": True, "ticket": req.ticket_identifier}


@app.get("/check-prs")
async def check_prs_endpoint():
    """
    Check whether any tracked new_model PRs have been merged and run the post-merge workflow.
    Call this from N8N on a schedule or triggered by a GitHub PR-merged webhook.
    """
    result = await check_merged_prs(linear, db, metabase, github)
    return result


class PostMergeRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    model_name: str          # e.g. "gold_fct_premium_concentration_hhi"
    ticket_identifier: str   # e.g. "GET-3"


@app.post("/post-merge")
async def post_merge_endpoint(req: PostMergeRequest):
    """
    Trigger the post-merge workflow directly (e.g. from GitHub Actions or N8N).
    Verifies the table exists, builds the Metabase dashboard, and closes the ticket.
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
