SCHEMA_CONTEXT = """
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
