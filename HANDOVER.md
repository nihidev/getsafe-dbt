# GetSafe Analytics Agent — Handover Document

**Date:** 2026-05-21  
**Author:** Claude (AI pair-programmer)  
**Project:** `/Users/dev/Developer/GetSafe/getsafe-dbt`

---

## 1. What Was Built

An end-to-end AI-driven analytics pipeline that turns a Linear ticket into a Metabase dashboard — automatically, with no human data engineering in the loop.

### The Flow

```
Stakeholder creates Linear ticket (label: analytics-request)
                    ↓
Agent polls Linear every 2 min (or triggered manually)
                    ↓
GPT-4o classifies intent → dashboard / data_quality / new_model / explore
                    ↓
Workflow executes:
  dashboard    → queries Supabase → creates Metabase chart + dashboard
  data_quality → runs dbt-equivalent SQL checks → markdown report
  new_model    → generates dbt SQL + yml → opens GitHub PR
  explore      → generates + runs SQL → plain-English summary
                    ↓
Result posted as comment on Linear ticket
Ticket moved to Done (or In Review for PRs)
Labels: auto-done ✅ or auto-error ❌
```

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────┐
│  LINEAR (GetSafe team)                              │
│  Ticket created → agent picks up → comment result  │
└─────────────┬───────────────────────────────────────┘
              │ GraphQL API (lin_api_...)
┌─────────────▼───────────────────────────────────────┐
│  FASTAPI AGENT  (Docker: getsafe_agent :8000)       │
│                                                     │
│  GPT-4o (OpenAI) — intent classification           │
│  + 4 workflow modules                               │
│  + polling loop (asyncio, every 120s)               │
└──────┬──────────────┬──────────────────┬────────────┘
       │              │                  │
  Supabase        Metabase API      GitHub REST API
  (psycopg2)      (X-API-Key)       (PAT: ghp_...)
  Gold layer      localhost:12345   nihidev/getsafe-dbt
       │
┌─────▼──────────────────────────────────────────────┐
│  STREAMLIT CHAT UI  (Docker: getsafe_chat_ui :8501) │
│  Tab 1: Free-form chat with tool-use agent          │
│  Tab 2: Linear ticket processor + polling trigger   │
└────────────────────────────────────────────────────┘
```

---

## 3. Technology Stack

| Layer | Tool | Purpose |
|-------|------|---------|
| Data warehouse | Supabase (PostgreSQL) | Stores bronze/silver/gold dbt models |
| Transformation | dbt CLI (`profiles.yml` → supabase target) | ELT pipeline |
| BI tool | Metabase (Docker, port 12345) | Dashboards and charts |
| AI brain | OpenAI GPT-4o | Intent classification, SQL generation, summarisation |
| Ticket system | Linear (GetSafe team) | Stakeholder requests |
| Code hosting | GitHub (`nihidev/getsafe-dbt`) | dbt model PRs |
| Agent API | FastAPI + uvicorn | Orchestration layer |
| Chat UI | Streamlit | Human-facing interface |
| Containers | Docker Compose | All services |

---

## 4. Data Models (dbt Gold Layer)

All tables in Supabase schema `public_gold`:

| Table | Grain | Key columns |
|-------|-------|-------------|
| `gold_fct_monthly_premiums` | party × month | written_premium, net_premium, refunded_premium, earned_premium, transaction_count |
| `gold_fct_accounting_reconciliation` | party × month | accounting_premium, finance_premium, delta, delta_pct, reconciliation_status |
| `gold_fct_customer_activity_daily` | user_id × activity_date | product_group, daily_premium, monthly_premium, churned_at |

---

## 5. File Structure

```
getsafe-dbt/
├── .env                          # All secrets (never commit)
├── docker-compose.yml            # Metabase (external) + Agent + Chat UI
├── Makefile                      # make up / down / build / logs
├── HANDOVER.md                   # This document
│
├── agent/
│   ├── main.py                   # FastAPI app, startup, /chat, /process-ticket, /poll-now
│   ├── polling.py                # Background asyncio polling loop + comment formatters
│   ├── intent_classifier.py      # GPT-4o classifies Linear ticket → intent JSON
│   ├── linear_client.py          # Linear GraphQL API (get tickets, comment, update state)
│   ├── github_client.py          # GitHub REST API (create branch, push file, open PR)
│   ├── metabase_client.py        # Metabase REST API (questions, dashboards, X-API-Key auth)
│   ├── db_client.py              # psycopg2 → Supabase (SELECT only, safe)
│   ├── tools.py                  # OpenAI function definitions (for chat mode)
│   ├── schema_context.py         # Gold layer schema fed into GPT-4o system prompt
│   ├── requirements.txt
│   ├── Dockerfile
│   └── workflows/
│       ├── dashboard.py          # Build SQL → create Metabase question + dashboard
│       ├── quality.py            # Run dbt-equivalent SQL checks → structured report
│       ├── explore.py            # GPT-4o generates SQL → runs → summarises in English
│       └── model.py              # GPT-4o generates dbt SQL + yml → GitHub PR
│
├── chat_ui/
│   ├── app.py                    # Streamlit: Chat tab + Linear Ticket Processor tab
│   ├── requirements.txt
│   └── Dockerfile
│
└── models/                       # dbt models
    ├── bronze/
    ├── silver/
    └── gold/
```

---

## 6. Environment Variables (`.env`)

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | GPT-4o API key |
| `OPENAI_MODEL` | Model name (default: gpt-4o) |
| `METABASE_API_KEY` | Metabase API key (mb_...) |
| `METABASE_URL` | Internal Docker URL (http://host.docker.internal:12345) |
| `METABASE_PUBLIC_URL` | Browser-facing URL (http://localhost:12345) |
| `SUPABASE_HOST` | aws-1-eu-west-2.pooler.supabase.com |
| `SUPABASE_USER` | postgres.wqpmvnqggqpoajbzmtcu |
| `SUPABASE_PASSWORD` | Supabase DB password |
| `SUPABASE_DB` | postgres |
| `GOLD_SCHEMA` | public_gold |
| `LINEAR_API_KEY` | lin_api_... (Personal API Key) |
| `LINEAR_TEAM_ID` | 5a12d787-f028-47d5-91bf-c7b9c45a4ecc (GetSafe team) |
| `GITHUB_PAT` | ghp_... (repo scope) |
| `GITHUB_REPO` | nihidev/getsafe-dbt |
| `POLL_INTERVAL_SECONDS` | 120 |
| `ENABLE_POLLING` | true |

---

## 7. Linear Setup

**Team:** GetSafe (`5a12d787-f028-47d5-91bf-c7b9c45a4ecc`)

**Labels created:**

| Label | Color | Meaning |
|-------|-------|---------|
| `analytics-request` | 🔵 Blue | Main trigger — agent polls for this |
| `dashboard` | 🟣 Purple | Create Metabase chart/dashboard |
| `data-quality` | 🟠 Orange | Run data quality audit |
| `new-model` | 🟢 Green | Generate dbt SQL + open GitHub PR |
| `explore` | 🩵 Teal | Answer data question in plain English |
| `auto-done` | ✅ Dark green | Agent completed successfully |
| `auto-error` | 🔴 Red | Agent failed — needs human review |

**Ticket states used:**

| State | Type | When |
|-------|------|------|
| Backlog / Todo | unstarted/backlog | Waiting to be picked up |
| In Progress | started | Agent is working on it |
| Done | completed | Dashboard/explore/quality complete |
| In Progress (stays) | started | New model — waiting for PR review |

---

## 8. API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Agent health check |
| `/chat` | POST | Free-form chat with tool-use agent |
| `/process-ticket` | POST | Process a specific Linear ticket by identifier |
| `/poll-now` | GET | Manually trigger one polling cycle |

---

## 9. How to Operate

### Start everything
```bash
cd /Users/dev/Developer/GetSafe/getsafe-dbt
make up       # starts agent (:8000) and chat UI (:8501)
```

### Stop
```bash
make down
```

### View logs
```bash
make logs          # all services
make agent-logs    # agent only
make ui-logs       # chat UI only
```

### Create a ticket manually
1. Open Linear → GetSafe team
2. Create issue with label `analytics-request` + one of `dashboard`, `data-quality`, `new-model`, `explore`
3. Write the request in plain English as the title
4. Either wait 2 minutes (auto-polling) or click **⚡ Poll now** in the Streamlit UI

### Force-process a specific ticket
```bash
curl -X POST http://localhost:8000/process-ticket \
  -H "Content-Type: application/json" \
  -d '{"ticket_identifier": "GET-1"}'
```

### Run dbt manually
```bash
cd /Users/dev/Developer/GetSafe/getsafe-dbt
dbt run --target supabase
dbt test --target supabase
```

---

## 10. Known Issues & Workarounds

| Issue | Workaround |
|-------|-----------|
| `auto-error` + `auto-done` both appear on first ticket | First run failed before the Metabase fix. Won't happen again on fresh tickets. Remove `auto-error` label manually on GET-1. |
| GitHub PAT stored in `.env` | Rotate the PAT (`ghp_...`) if it expires. Update `.env` → `make up` (no rebuild needed). |
| Metabase session vs API key | We use `X-API-Key` header. If Metabase is restarted, the key persists — no re-auth needed. |
| dbt runs manually for now | After merging a `new-model` PR, run `dbt run -s <model_name> --target supabase` by hand. |
| Polling catches Backlog + Todo | Both state types are included so tickets created in either state are picked up. |

---

## 11. Next Steps (Prioritised)

### Immediate (1–2 days)
- [ ] **Connect N8N webhook** — replace 2-min polling with instant Linear webhook trigger via N8N. Eliminates the delay and removes the polling infrastructure.
- [ ] **Test all 4 intent workflows** — create one ticket of each type (dashboard, data-quality, new-model, explore) and verify end-to-end.
- [ ] **Add `dbt run` trigger** — after a `new-model` PR is merged, auto-run dbt via a GitHub Actions workflow (push to `main` → dbt Cloud job runs → Supabase updated).

### Short term (1–2 weeks)
- [ ] **Multi-table dashboard workflow** — current dashboard workflow builds a single chart. Extend to build multi-chart dashboards when the request spans multiple tables.
- [ ] **Error retry logic** — if the agent fails (LLM timeout, Supabase blip), re-queue the ticket after 10 minutes rather than leaving it in `auto-error`.
- [ ] **Stakeholder email/Slack notification** — after the agent comments on the ticket, send an email or Slack message to the assignee with the dashboard link.
- [ ] **Schema auto-discovery** — instead of hardcoded schema context in the system prompt, dynamically read `_models.yml` at startup so new dbt models are automatically known to the agent.

### Medium term (1 month)
- [ ] **Multi-tenant support** — parameterise `LINEAR_TEAM_ID`, `GOLD_SCHEMA`, `GITHUB_REPO` so any company can plug in their setup. This is the core of the product vision.
- [ ] **Anomaly detection model** — a scheduled dbt model that flags when `written_premium` drops >20% month-over-month. Agent posts a proactive Linear ticket — no human triggers required.
- [ ] **dbt Cloud API integration** — trigger dbt Cloud jobs via API instead of CLI, enabling job status tracking and failure alerts posted back to Linear.
- [ ] **Data catalog** — auto-generate column descriptions from `_models.yml` and expose them via the chat UI so stakeholders can self-serve schema discovery.

### Vision (the product)
- [ ] **MCP server** — expose the entire pipeline as an MCP so any AI assistant (Claude, Cursor, etc.) can trigger it as a tool.
- [ ] **Onboarding wizard** — Streamlit page where a new customer enters their Linear key, Supabase URL, GitHub repo, and Metabase URL → agent auto-configures itself.
- [ ] **Usage analytics** — track which ticket types are most common, which dashboards get viewed, which models are auto-generated → feed back into improving the classifier.

---

## 12. Credentials Reference

> **Never commit `.env` to git.** The `.gitignore` should exclude it.

| Secret | Rotate at |
|--------|-----------|
| `OPENAI_API_KEY` | platform.openai.com/api-keys |
| `METABASE_API_KEY` | Metabase → Admin → API Keys |
| `LINEAR_API_KEY` | linear.app → Settings → API → Personal API Keys |
| `GITHUB_PAT` | github.com/settings/tokens |
| `SUPABASE_PASSWORD` | supabase.com → Project Settings → Database |

---

*Built in one session using Claude Code with Linear MCP, Supabase MCP, OpenAI GPT-4o, Metabase REST API, and GitHub REST API.*

---
  What Was Fixed — End to End

  Security

  ┌────────────────────────────────────┬───────────────────────────────────────────────────────────────────────┬───────────────────────────────┐
  │                 #                  │                                  Fix                                  │             File              │
  ├────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┼───────────────────────────────┤
  │ SQL injection in _get_table_stats  │ Replaced string interpolation with query_safe() parameterized queries │ checks.py (new), db_client.py │
  ├────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┼───────────────────────────────┤
  │ SQL injection in dashboard filters │ Whitelist of allowed keys + regex-validated values                    │ workflows/dashboard.py        │
  └────────────────────────────────────┴───────────────────────────────────────────────────────────────────────┴───────────────────────────────┘

  Reliability

  ┌──────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────┬──────────────────────────────────────┐
  │                  #                   │                                    Fix                                     │                 File                 │
  ├──────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┤
  │ _tracked_prs lost on restart         │ Persisted to public.agent_tracked_prs table; loaded back at startup        │ db_client.py, polling.py             │
  ├──────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┤
  │ Circular import quality.py → main.py │ Extracted checks into standalone checks.py                                 │ checks.py (new), quality.py, main.py │
  ├──────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┤
  │ Intent output not validated          │ Added VALID_INTENTS guard with explore fallback                            │ intent_classifier.py                 │
  ├──────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┤
  │ get_ticket swallows all exceptions   │ Only catches RuntimeError (GraphQL not-found); network errors propagate    │ linear_client.py                     │
  ├──────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┤
  │ Idempotency — ticket processed twice │ Guard at top of process_ticket skips if auto-done/auto-error label present │ polling.py                           │
  └──────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────┴──────────────────────────────────────┘

  Performance

  ┌─────────────────────────────────┬──────────────────────────────────────────────────────────┬──────────────┐
  │                #                │                           Fix                            │     File     │
  ├─────────────────────────────────┼──────────────────────────────────────────────────────────┼──────────────┤
  │ New connection per query        │ ThreadedConnectionPool(min=1, max=5) reused across calls │ db_client.py │
  ├─────────────────────────────────┼──────────────────────────────────────────────────────────┼──────────────┤
  │ OpenAI calls could hang forever │ timeout=60.0 on the client                               │ main.py      │
  └─────────────────────────────────┴──────────────────────────────────────────────────────────┴──────────────┘

  Architecture

  ┌────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────┬───────────────────────────────────────────────────────────┐
  │                   #                    │                                    Fix                                     │                           File                            │
  ├────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┤
  │ Polling removed                        │ Startup no longer spawns the polling loop; /poll-now endpoint gone         │ main.py, polling.py                                       │
  ├────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┤
  │ New /check-prs endpoint                │ N8N calls this when a PR merges (or on a schedule)                         │ main.py                                                   │
  ├────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┤
  │ @app.on_event("startup") deprecated    │ Replaced with lifespan context manager                                     │ main.py                                                   │
  ├────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┤
  │ 3 copies of schema context             │ Single source in schemas.py (SCHEMA_CONTEXT, EXPLORE_SCHEMA, MODEL_SCHEMA) │ schemas.py (new), schema_context.py, explore.py, model.py │
  ├────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┤
  │ GitHub Actions heredoc indentation bug │ Content moved to column 0 — YAML now unambiguously valid                   │ .github/workflows/dbt_post_merge.yml                      │
  ├────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┤
  │ No Docker healthcheck                  │ Python urllib health check on /health; chat_ui waits for service_healthy   │ docker-compose.yml                                        │
  ├────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────┤
  │ .env could be baked into image         │ Added agent/.dockerignore                                                  │ .dockerignore (new)                                       │
  └────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────┘

  UI

  - Removed "Poll now" button, replaced with "Check merged PRs" that calls /check-prs
  - Updated copy to reflect N8N webhook flow

  N8N setup you'll need: create two workflows — (1) Linear webhook (ticket created with analytics-request label) → POST http://<agent>:8000/process-ticket with {"ticket_identifier": "{{issueIdentifier}}"}, and (2) GitHub webhook (PR closed + merged on auto/ branch) → GET
  http://<agent>:8000/check-prs.