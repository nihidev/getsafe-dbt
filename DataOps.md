# DataOps Platform — Product Vision & Market Analysis

**Date:** 2026-05-22
**Status:** Vision document — pre-build

---

## Table of Contents

1. [What We Are Building](#1-what-we-are-building)
2. [Target Architecture](#2-target-architecture)
3. [Phase-by-Phase Build Plan](#3-phase-by-phase-build-plan)
4. [Packaging & Distribution](#4-packaging--distribution)
5. [Market Analysis](#5-market-analysis)
6. [Commercial Strategy](#6-commercial-strategy)
7. [Risks & Mitigations](#7-risks--mitigations)
8. [Recommended Next Steps](#8-recommended-next-steps)

---

## 1. What We Are Building

A self-hosted **analytics ops platform** that any company can install in one command, connect their tools, and get a fully automated Linear → DB → dbt → Metabase → N8N pipeline running — with no data engineering required.

The core value proposition: a stakeholder creates a plain-English ticket in their project management tool. The agent reads it, classifies the intent, executes the correct workflow (build a dashboard, audit data quality, generate a dbt model, answer a data question), and posts the result back on the ticket — automatically, end to end.

### The Flow

```
Stakeholder creates Linear ticket (label: analytics-request)
                    ↓
N8N webhook fires instantly (or agent polls every 2 min)
                    ↓
GPT-4o classifies intent → dashboard / data_quality / new_model / explore
                    ↓
Workflow executes:
  dashboard     → queries DB → creates Metabase chart + dashboard
  data_quality  → runs dbt-equivalent SQL checks → markdown report
  new_model     → generates dbt SQL + yml → opens GitHub PR
  explore       → generates + runs SQL → plain-English summary
                    ↓
Result posted as comment on Linear ticket
Ticket moved to Done (or In Review for PRs)
Labels: auto-done ✅ or auto-error ❌
```

---

## 2. Target Architecture

### What the Installed Stack Looks Like

```
User runs:
  npx create-analytics-agent   (or: pip install analytics-agent && analytics init)
                    ↓
  Interactive onboarding CLI / Streamlit wizard
  Collects: DB type, DB URL, Linear key, GitHub PAT, Metabase admin pwd
                    ↓
  Generates docker-compose.yml + .env + dbt profiles.yml
                    ↓
  docker compose up  (pulls versioned images from Docker Hub)
                    ↓
  ┌──────────────────────────────────────────────┐
  │  Container stack (all auto-started)          │
  │                                              │
  │  agent      :8000  ← FastAPI orchestrator    │
  │  chat_ui    :8501  ← Streamlit UI            │
  │  metabase   :3000  ← BI dashboards           │
  │  n8n        :5678  ← Workflow orchestration  │
  └──────────────────────────────────────────────┘
                    ↓
  N8N auto-imports workflow templates:
    • Linear webhook → agent /process-ticket
    • GitHub merge  → agent /check-prs
                    ↓
  User opens localhost:8501, pastes their first Linear ticket title
  → agent handles it end to end
```

### Technology Stack

| Layer | Tool | Purpose |
|-------|------|---------|
| Ticket system | Linear (+ Jira in v2) | Stakeholder requests — the trigger |
| AI brain | OpenAI GPT-4o | Intent classification, SQL generation, summarisation |
| Agent API | FastAPI + uvicorn | Orchestration layer |
| Chat UI | Streamlit | Human-facing interface |
| Workflow orchestration | N8N | Webhook routing, event-driven triggers |
| Data warehouse | Postgres / BigQuery / Snowflake / Redshift / DuckDB | Any company's existing warehouse |
| Transformation | dbt CLI | ELT pipeline, model generation |
| BI tool | Metabase | Auto-generated dashboards and charts |
| Code hosting | GitHub | dbt model PRs, version control |
| Containers | Docker Compose | All services, single-command startup |

---

## 3. Phase-by-Phase Build Plan

---

### Phase 1 — Multi-Tenant Config Layer (Week 1–2)

**Goal:** Replace every hardcoded value with a config schema that can be set per-tenant.

Replace the flat `.env` with a `TenantConfig` Pydantic model:

```python
class TenantConfig(BaseModel):
    linear_api_key: str
    linear_team_id: str
    github_pat: str
    github_repo: str
    metabase_url: str
    metabase_api_key: str
    db_type: Literal["postgres", "bigquery", "snowflake", "redshift", "duckdb"]
    db_connection: dict        # connector-specific fields
    gold_schema: str
    openai_api_key: str
    openai_model: str = "gpt-4o"
```

Add `GET /config` and `POST /config` endpoints — read/write config to `config.json` (or a `agent_config` table if the DB is Postgres). The Streamlit wizard tab already exists structurally; it just needs the form fields wired to this endpoint.

**Effort:** ~3 days.

---

### Phase 2 — DB Adapter Layer (Week 2–4)

**Goal:** Make `db_client.py` connector-agnostic so any warehouse works.

```
agent/connectors/
  __init__.py      # factory: get_connector(db_type, db_connection)
  base.py          # abstract BaseConnector: execute(), tables(), columns()
  postgres.py      # psycopg2 (current code, refactored)
  bigquery.py      # google-cloud-bigquery
  snowflake.py     # snowflake-connector-python
  redshift.py      # redshift_connector
  duckdb.py        # duckdb (local/dev use)
```

Each connector implements a common interface:

```python
class BaseConnector:
    def execute(self, sql: str, params=None) -> list[dict]: ...
    def tables(self, schema: str) -> list[str]: ...
    def columns(self, schema: str, table: str) -> list[dict]: ...
```

Add `agent/dbt_profile_generator.py` — emits the correct `profiles.yml` block per connector type so `dbt run` works for any warehouse without manual config.

**Effort:** ~1 week. Postgres + DuckDB are trivial (code exists). BigQuery and Snowflake need auth flows (service account JSON, OAuth).

---

### Phase 3 — N8N Auto-Wiring (Week 3–4)

**Goal:** N8N starts with Linear and GitHub workflows pre-loaded. Zero manual setup.

Add N8N to `docker-compose.yml`:

```yaml
n8n:
  image: n8nio/n8n:1.40.0   # pinned version
  ports: ["5678:5678"]
  environment:
    - N8N_BASIC_AUTH_ACTIVE=true
    - N8N_BASIC_AUTH_USER=${N8N_USER}
    - N8N_BASIC_AUTH_PASSWORD=${N8N_PASSWORD}
    - WEBHOOK_URL=http://host.docker.internal:5678
  volumes:
    - n8n_data:/home/node/.n8n
    - ./n8n/workflows:/workflows
```

Add two pre-built workflow JSON files in `n8n/workflows/`:
- `linear_webhook.json` — Linear webhook trigger → POST to `/process-ticket`
- `github_merge.json` — GitHub PR merge trigger → GET `/check-prs`

Add `agent/n8n_bootstrap.py` — on startup, calls the N8N REST API to import the workflow JSONs if not already imported (idempotent). Also registers the Linear webhook URL via the Linear API automatically so the user never has to touch Linear's webhook settings.

**Effort:** ~3 days.

---

### Phase 4 — Metabase Auto-Setup (Week 4–5)

**Goal:** Metabase initialises with the DB connection already configured. No manual first-run wizard.

Metabase exposes a `/api/setup` endpoint that runs the first-time wizard programmatically. Add `agent/metabase_bootstrap.py`:

```python
async def bootstrap_metabase(config: TenantConfig):
    # 1. POST /api/setup with admin credentials + DB connection details
    # 2. GET /api/api-key to generate an API key
    # 3. Write the key back to config.json
    # 4. Set bootstrapped=True in config so this never re-runs
```

Called once at agent startup if `METABASE_API_KEY` is not yet set.

**Effort:** ~2 days.

---

### Phase 5 — Packaging (Week 5–6)

**Goal:** One command to get the whole stack running.

#### Option A — Python CLI (recommended for technical users)

```bash
pip install analytics-agent

analytics init    # interactive wizard → writes .env + docker-compose.yml
analytics up      # docker compose up -d
analytics status  # health-checks all 4 services
analytics logs    # tail logs
```

Built with [Typer](https://typer.tiangolo.com/). The `init` command is a guided questionnaire (DB type, credentials, Linear key, GitHub PAT) that outputs a ready-to-run environment.

#### Option B — npx bootstrapper (recommended for broader reach)

```bash
npx create-analytics-agent my-company
```

A small Node.js script using `inquirer` that asks the same questions, writes `.env` + `docker-compose.yml`, and runs `docker compose up -d`. Published to npm as `create-analytics-agent`. The Docker images are Python — npm just handles the setup UX.

#### Docker Hub publishing

GitHub Actions workflow:
```yaml
on:
  push:
    tags: ["v*.*.*"]
jobs:
  build:
    - docker buildx build --platform linux/amd64,linux/arm64
    - push yourdockerhub/analytics-agent:${{ github.ref_name }}
    - push yourdockerhub/analytics-agent:latest
    - push yourdockerhub/analytics-ui:${{ github.ref_name }}
    - push yourdockerhub/analytics-ui:latest
```

**Effort:** ~1 week.

---

### Phase 6 — Schema Auto-Discovery (Week 6–7)

**Goal:** The GPT-4o system prompt is always current — no hardcoded schema context.

Replace the static `schemas.py` with a live introspection layer:

```python
async def build_schema_context(connector: BaseConnector, gold_schema: str) -> str:
    tables = connector.tables(gold_schema)
    context_parts = []
    for table in tables:
        cols = connector.columns(gold_schema, table)
        context_parts.append(
            f"Table: {table}\nColumns: {', '.join(c['name'] for c in cols)}"
        )
    return "\n\n".join(context_parts)
```

Called at agent startup and cached with a 5-minute TTL. New dbt models are automatically known to the agent without any code changes.

**Effort:** ~1 day (the connector layer from Phase 2 makes this trivial).

---

### What a User Gets After All Six Phases

```
$ analytics init

  DB type?          postgres
  DB connection?    postgresql://user:pass@host:5432/mydb
  Linear API key?   lin_api_...
  Linear team?      MyCompany
  GitHub repo?      myorg/analytics
  GitHub PAT?       ghp_...
  OpenAI API key?   sk-...

  ✓ Config written to .env
  ✓ docker-compose.yml generated
  ✓ dbt profiles.yml generated

$ analytics up

  ✓ agent      running on :8000
  ✓ chat_ui    running on :8501
  ✓ metabase   running on :3000  (DB connection auto-configured)
  ✓ n8n        running on :5678  (Linear + GitHub workflows imported)
  ✓ Linear webhook registered
  ✓ Schema context loaded (4 tables, 31 columns)

  Opening http://localhost:8501 ...
```

From that point: stakeholder creates a Linear ticket → result appears on the ticket in under 60 seconds. No human data engineering in the loop.

---

## 4. Packaging & Distribution

### Release Tiers

| Tier | Model | Target |
|------|-------|--------|
| **Open source** | MIT licence, Docker Compose, self-hosted | Developers, data engineers evaluating |
| **Managed cloud** | SaaS, user supplies credentials, we run infra | Startups that don't want to manage Docker |
| **Enterprise** | SSO, audit logs, Jira, Tableau/Looker, Slack | 200+ person companies, procurement budgets |

### Why Open Source First

dbt's playbook: dbt Core is free and open-source. dbt Cloud is $100–500/month per seat. Community adoption drove commercial conversion. The data engineering community distrusts closed-source products — open-sourcing the core removes that barrier entirely and provides organic distribution through GitHub stars, blog posts, and conference talks.

---

## 5. Market Analysis

### The Problem Score: 8/10

Data teams at growth-stage companies spend 60–70% of their time on ad-hoc stakeholder requests — dashboard asks, data questions, one-off SQL reports. The "ticket to insight" latency at most companies is 1–2 weeks. Every data engineer at a Series A–C company recognises this pain immediately. It is well-documented, expensive, and unsolved at scale.

### This Product As-Is: 5/10

The engineering is solid. The market fit concern is stack narrowness.

| Weakness | Impact |
|----------|--------|
| **Linear only** | Linear has ~5% project management market share. Jira has 65%+. Excluding Jira means excluding 95% of the addressable market. |
| **Opinionated stack** | Requires Linear + Supabase/Postgres + dbt + Metabase + GitHub + N8N simultaneously. Any company missing one of these six cannot use the product without significant effort. |
| **Crowded AI data space** | Dot, TextQL, Defog, Outerbase, Julius AI, Hex, and Secoda all raised $10M–$50M+ solving adjacent problems in 2023–2025. |
| **Self-hosted friction** | The ideal buyer (a 3-person data team at a 100-person startup) does not want to manage Docker infrastructure. They want SaaS. |
| **dbt dependency** | Only companies that have already adopted dbt can fully benefit. A meaningful but still minority segment. |

### With Jira Support + Cloud Hosting: 7.5/10

These two changes are the difference between a niche tool and a sellable product.

---

### Competitive Landscape

| Competitor | Funding | What they do | Our differentiation |
|------------|---------|--------------|---------------------|
| **Hex** | $52M | AI-powered analytics notebooks | We automate ops workflows, not notebook exploration |
| **Dot (Data Dot)** | $10M | AI data analyst, Slack interface | We close the loop end-to-end: ticket → dashboard → PR |
| **Secoda** | $14M | Data catalog + AI search | We execute, not just discover |
| **TextQL** | $4M | Natural language to SQL | We generate dbt models, PRs, and Metabase dashboards — not just SQL |
| **Atlan** | $105M | Enterprise data catalog | Enterprise-only, $50K+ ACV, not self-serve |
| **dbt Cloud** | $222M | Managed dbt transformation | Transformation only; no ticket integration, no dashboard creation |
| **Lightdash** | $17M | Open-source Metabase + dbt | BI only; no ops automation |
| **N8N** | $22M | Workflow automation | Infrastructure layer; no analytics intelligence |

**The gap:** Nobody owns the full workflow from stakeholder ticket to shipped dashboard with generated dbt model. Most tools solve one layer. This product solves all layers.

---

### Ideal Customer Profile (ICP)

**Today (v1, self-hosted):**
- Series A or B tech startup, 50–300 employees
- Engineering-led culture, uses Linear
- 1–3 person data team overwhelmed with requests
- Already adopted dbt + a cloud data warehouse
- Values data sovereignty / GDPR compliance (prefers self-hosted)
- Estimated addressable market: 2,000–5,000 companies globally

**After Jira + cloud hosting (v2):**
- Any tech company, 50–1,000 employees
- Uses Jira or Linear
- Has a data team of any size
- Estimated addressable market: 50,000–100,000 companies globally

---

### Pricing Benchmarks

| Tier | Price | Basis |
|------|-------|-------|
| Open source | Free | Community, awareness, inbound |
| Managed cloud starter | $299/month | Up to 3 users, 1 warehouse |
| Managed cloud growth | $799/month | Up to 10 users, unlimited warehouses |
| Enterprise | $2,000–5,000/month | SSO, SLA, Jira, Tableau/Looker, Slack |

A company with a 2-person data team saves roughly 10–15 hours/week in manual request handling. At a fully-loaded cost of €80/hour, that is €3,200–4,800/month in recovered engineering time. Pricing at $799/month is a 4–6x ROI argument — straightforward to sell.

---

## 6. Commercial Strategy

### Phase 1 — Traction (Months 1–3)

- Launch open-source on GitHub with a clear README and a 3-minute demo video
- Post in dbt Slack (#tools-and-integrations), Linear community, Hacker News (Show HN)
- Target: 200 GitHub stars, 20 active self-hosters
- Instrument the agent to collect anonymous usage telemetry (opt-in) — ticket types processed, intent distribution, error rates

### Phase 2 — Revenue (Months 3–6)

- Launch managed cloud at $299/month (waitlist from open-source users)
- Add Jira support — immediately unlocks enterprise pipeline
- Build a Slack interface so non-Linear users can trigger the agent via Slack messages
- Target: 20 paying customers, $6,000 MRR

### Phase 3 — Scale (Months 6–12)

- Add Tableau/Looker alongside Metabase
- Add BigQuery and Snowflake connectors (largest warehouse market share)
- Enterprise tier with SSO and audit logs
- Target: 100 paying customers, $50,000 MRR

### Distribution Channels

| Channel | Why it works |
|---------|-------------|
| **dbt Slack** | 35,000+ data practitioners, highly receptive to tools that extend dbt |
| **Linear community** | Early adopters, engineering-led, high willingness to pay for tooling |
| **Hacker News Show HN** | Strong for open-source developer tools at launch |
| **Conference talks** | dbt Coalesce, Data Council — demo the end-to-end workflow live |
| **GitHub** | Stars compound; other tools reference you; SEO |

---

## 7. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Metabase first-run API is fragile / changes | Medium | Medium | `--skip-metabase-bootstrap` flag; user can connect manually in Metabase UI |
| Snowflake / BigQuery auth complexity blocks adoption | High | High | Ship v1 with Postgres + DuckDB only; add cloud warehouses in v1.1 |
| Well-funded competitor copies the approach | Medium | High | Speed to open-source launch; community moat; deeper workflow integration |
| N8N workflow JSON format changes between versions | Low | Medium | Pin N8N to a specific Docker image tag in the compose template |
| GPT-4o cost makes per-ticket economics unprofitable | Low | Medium | Add model selection; allow users to provide their own API key |
| Linear's market share is too small | High | High | Add Jira support before v2 launch — this is the single most important non-negotiable |
| Credentials in `.env` are a security risk in shared environments | Low | High | v2: offer HashiCorp Vault and AWS Secrets Manager integration |
| Self-hosted means customer manages infrastructure | High | Medium | Build managed cloud tier; position self-hosted as the "evaluation" path |

---

## 8. Recommended Next Steps

Ordered by impact-to-effort ratio:

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| 1 | Refactor `.env` → `TenantConfig` Pydantic model + `POST /config` endpoint | 1 day | Foundation for everything else |
| 2 | Add N8N to `docker-compose.yml` + auto-import the two workflow JSONs | 2 days | Eliminates 2-min polling lag; biggest immediate UX improvement |
| 3 | Build `analytics init` CLI with Typer | 3 days | Transforms setup from a 30-minute manual process to a 3-minute guided wizard |
| 4 | Publish Docker images to Docker Hub via GitHub Actions | 2 days | Makes the product installable by anyone without a local code checkout |
| 5 | Add Jira support in `linear_client.py` → `ticket_client.py` | 1 week | Unlocks 10x the addressable market |
| 6 | DB adapter layer (Postgres + DuckDB first) | 1 week | Makes the product warehouse-agnostic |
| 7 | Schema auto-discovery (replaces hardcoded `schemas.py`) | 1 day | Agent always knows current schema; works for any customer's tables |
| 8 | Metabase bootstrap API (`metabase_bootstrap.py`) | 2 days | Eliminates the one remaining manual setup step |

**Honest total timeline to a shippable, sellable v1:** 6–8 weeks of focused effort.

The hardest 80% of the engineering is already built. What remains is parameterisation, abstraction, and packaging — not novel technology.

---

*Document authored: 2026-05-22. Next review: after Phase 2 (DB adapter layer) is complete.*
