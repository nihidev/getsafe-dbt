import os

GOLD = os.environ.get("GOLD_SCHEMA", "public_gold")

# ── Chat / explore prompts (concise) ─────────────────────────────────────────

SCHEMA_CONTEXT = f"""
You have access to a Supabase PostgreSQL database with three Gold layer tables built by dbt.
Always prefix table names with the schema name provided below.

=== gold_fct_monthly_premiums ===
Grain: one row per (party, month)
Use for: premium reporting, Finance vs Accounting, revenue trends

Columns:
  party               VARCHAR  — insurance partner: berlinre, dronant, getland, liadigital
  month               VARCHAR  — YYYY-MM format (e.g., '2025-06')
  premium             NUMERIC  — gross written premium in EUR
  written_premium     NUMERIC  — same as premium (alias for joins)
  refunded_premium    NUMERIC  — sum of refunded amounts in the period
  refund_count        INTEGER  — number of refund transactions
  net_premium         NUMERIC  — written_premium minus refunded_premium
  earned_premium      NUMERIC  — prorated premium by days remaining in month
  transaction_count   INTEGER  — number of processed transactions
  first_transaction_date DATE
  last_transaction_date  DATE
  _created_at         TIMESTAMP

=== gold_fct_accounting_reconciliation ===
Grain: one row per (party, month)
Use for: Finance vs Accounting gap analysis, discrepancy detection

Columns:
  party                   VARCHAR  — insurance partner
  month                   VARCHAR  — YYYY-MM format
  accounting_premium      NUMERIC  — Accounting team figure (source of truth)
  finance_premium         NUMERIC  — derived from transaction data
  net_premium             NUMERIC  — net written premium
  refunded_premium        NUMERIC  — refunded amounts
  net_delta               NUMERIC  — net_premium minus accounting_premium
  transaction_count       INTEGER
  delta                   NUMERIC  — finance_premium minus accounting_premium
  delta_pct               NUMERIC  — abs(delta) as % of accounting_premium
  reconciliation_status   VARCHAR  — MATCH, NEAR_MATCH, or DISCREPANCY
  is_reconciled           BOOLEAN  — true if delta < 0.01
  _reconciled_at          TIMESTAMP

=== gold_fct_customer_activity_daily ===
Grain: one row per (user_id, activity_date)
Use for: customer KPIs, churn analysis, daily/monthly premium tracking

Columns:
  activity_date           DATE     — calendar date
  user_id                 VARCHAR  — customer identifier (e.g., USR001)
  product_group           VARCHAR  — liability, household, legal
  acquisition_date        DATE     — customer acquisition date
  started_at              DATE     — policy start date
  churned_at              DATE     — policy end date (NULL if active)
  daily_premium           NUMERIC  — monthly_premium / days_in_month
  monthly_premium         NUMERIC  — monthly premium amount in EUR
  days_since_acquisition  INTEGER
  activity_month          VARCHAR  — YYYY-MM partition bucket
  _loaded_at              TIMESTAMP
"""

# ── Explore / SQL-gen prompts (one-liner per table) ───────────────────────────

EXPLORE_SCHEMA = f"""Gold layer tables (schema: {GOLD}):
- gold_fct_monthly_premiums       — party, month (VARCHAR YYYY-MM — use LIKE/string ops, NOT EXTRACT), written_premium, net_premium, refunded_premium, earned_premium, transaction_count
- gold_fct_accounting_reconciliation — party, month (VARCHAR YYYY-MM), accounting_premium, finance_premium, delta, delta_pct, reconciliation_status
- gold_fct_customer_activity_daily  — user_id, activity_date (DATE), product_group, daily_premium, monthly_premium, churned_at, days_since_acquisition"""

# ── dbt model generation (detailed with ref() syntax and exact types) ─────────

MODEL_SCHEMA = f"""Available dbt models and EXACT column names:

ref('gold_fct_monthly_premiums') → {GOLD}.gold_fct_monthly_premiums
  Grain: party × month | Use this for any party-level premium aggregation or market share analysis
  Columns: party (varchar), month (text YYYY-MM), written_premium (numeric), refunded_premium (numeric),
           net_premium (numeric), earned_premium (numeric), transaction_count (bigint),
           first_transaction_date (date), last_transaction_date (date), _created_at (timestamptz)

ref('gold_fct_customer_activity_daily') → {GOLD}.gold_fct_customer_activity_daily
  Grain: user_id × activity_date
  Columns: activity_date (date), user_id (text), product_group (text: household/legal/liability),
           acquisition_date (date), started_at (date), churned_at (date — null means active),
           daily_premium (numeric), monthly_premium (numeric), days_since_acquisition (int),
           activity_month (text), _loaded_at (timestamptz)

ref('gold_fct_accounting_reconciliation') → {GOLD}.gold_fct_accounting_reconciliation
  Grain: party × month
  Columns: party, month, accounting_premium, finance_premium, net_premium, refunded_premium,
           net_delta, delta, delta_pct, reconciliation_status, is_reconciled, transaction_count

ref('silver_transactions') → public_silver.silver_transactions
  Use ONLY when the requirement explicitly asks for raw transaction-level data
  Columns: transaction_id, created_at_ts, transaction_date, transaction_month (text YYYY-MM),
           premium_amount (float8), premium_currency, party, status (valid: 'processed','process'),
           _status_normalized (bool), _is_clean (bool)

Seeds:
ref('accounting_closing') → accounting_closing
  Columns: party (varchar), month (varchar), accounting_premium (double precision)"""
