import json
import logging
import os
import re

from openai import OpenAI

from schemas import MODEL_SCHEMA as _SCHEMA

logger = logging.getLogger(__name__)

GOLD = os.environ.get("GOLD_SCHEMA", "public_gold")

# Maps {{ ref('x') }} → real schema.table for EXPLAIN validation
_REF_MAP = {
    "gold_fct_monthly_premiums":          f"{GOLD}.gold_fct_monthly_premiums",
    "gold_fct_accounting_reconciliation": f"{GOLD}.gold_fct_accounting_reconciliation",
    "gold_fct_customer_activity_daily":   f"{GOLD}.gold_fct_customer_activity_daily",
    "silver_transactions":                "public_silver.silver_transactions",
    "accounting_closing":                 "public_seeds.accounting_closing",
}


def _resolve_refs(sql: str) -> str:
    """Replace {{ ref('x') }} with real schema.table; strip remaining Jinja blocks."""
    def _sub(m):
        model = re.sub(r"['\"]", "", m.group(1)).strip()
        return _REF_MAP.get(model, f"{GOLD}.{model}")
    sql = re.sub(r"\{\{\s*ref\(([^)]+)\)\s*\}\}", _sub, sql)
    sql = re.sub(r"\{\{[^}]+\}\}", "", sql)  # strip {{ config(...) }} etc.
    return sql


def _validate_syntax(sql: str, db) -> tuple[bool, str]:
    """Run EXPLAIN against Supabase. Returns (is_valid, error_message)."""
    resolved = _resolve_refs(sql)
    result = db.explain_sql(resolved)
    if result.get("valid"):
        return True, ""
    return False, result.get("error", "Unknown SQL error")


def _self_review(sql: str, requirement: str, openai_client: OpenAI) -> list[str]:
    """Ask GPT-4o to review its own output for logic and completeness errors."""
    resp = openai_client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        messages=[{"role": "user", "content": f"""Review this dbt SQL model for correctness.

{_SCHEMA}

Requirement: {requirement}

Generated SQL:
{sql}

Check for:
1. Wrong table references (e.g. using silver when gold already has the aggregation)
2. Missing required output columns stated in the requirement
3. Logic errors (wrong formula, missing multiplier, wrong filter values)
4. Missing NULLIF guards on denominators in division

Return ONLY valid JSON: {{"issues": ["...", "..."]}} — or {{"issues": []}} if no problems found."""}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    try:
        data = json.loads(resp.choices[0].message.content)
        return data.get("issues", [])
    except Exception:
        return []


def _fix_sql(sql: str, requirement: str, issues: list[str], openai_client: OpenAI) -> str:
    issue_list = "\n".join(f"- {i}" for i in issues)
    resp = openai_client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        messages=[{"role": "user", "content": f"""Fix this dbt SQL model.

{_SCHEMA}

Requirement: {requirement}

Issues to fix:
{issue_list}

Original SQL:
{sql}

Return ONLY the corrected SQL — no markdown fences, no explanation."""}],
        temperature=0,
    )
    fixed = resp.choices[0].message.content.strip()
    return fixed.replace("```sql", "").replace("```", "").strip()


def _gen_sql(model_name: str, requirement: str, openai_client: OpenAI) -> str:
    resp = openai_client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        messages=[{"role": "user", "content": f"""Generate a production-quality dbt SQL model named '{model_name}'.

{_SCHEMA}

Requirement: {requirement}

Rules:
- First line: {{{{ config(materialized='table', tags=['gold']) }}}}
- Use {{{{ ref('model_name') }}}} for ALL table references — never hardcode a schema name
- Use NULLIF(x, 0) to guard every division denominator
- Use POWER(x, 2) not x*x when squaring
- Use ROUND(...::numeric, 2) for all monetary/percentage columns
- Last column of final SELECT must be: NOW() AS _created_at
- Return ONLY raw SQL — no markdown fences, no explanation"""}],
        temperature=0,
    )
    sql = resp.choices[0].message.content.strip()
    return sql.replace("```sql", "").replace("```", "").strip()


def _gen_yml(model_name: str, requirement: str, sql: str, openai_client: OpenAI) -> str:
    resp = openai_client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        messages=[{"role": "user", "content": f"""Generate a dbt _models.yml entry for model '{model_name}'.

Requirement: {requirement}

SQL (derive the exact output columns from this):
{sql}

Rules:
- Start with: - name: {model_name}
- Write a clear description
- Document EVERY column in the final SELECT with a description
- not_null tests on all key columns
- For columns with a fixed set of allowed values use EXACTLY this accepted_values syntax:
      - accepted_values:
          arguments:
            values: ['val1', 'val2', 'val3']
- For grain uniqueness add a model-level test block:
  tests:
    - dbt_utils.unique_combination_of_columns:
        arguments:
          combination_of_columns: ['col1', 'col2']
- Do NOT add a config block — materialization and schema are set in dbt_project.yml
- Return ONLY yaml starting with '- name:' — no fences, no explanation"""}],
        temperature=0,
    )
    yml = resp.choices[0].message.content.strip()
    return yml.replace("```yaml", "").replace("```yml", "").replace("```", "").strip()


def run(intent: dict, github, db, ticket_identifier: str, openai_client: OpenAI) -> dict:
    pat = os.environ.get("GITHUB_PAT", "")
    if not pat or pat == "PASTE_YOUR_GITHUB_PAT_HERE":
        return {"success": False, "error": "GitHub PAT not configured."}

    requirement = intent.get("metric") or "new analytics model"
    raw_name = intent.get("model_name") or re.sub(r"[^a-z0-9]", "_", requirement.lower())[:40]
    model_name = f"gold_fct_{raw_name}" if not raw_name.startswith("gold_") else raw_name
    branch = f"auto/{ticket_identifier.lower()}-{model_name}"

    # ── Step 1: Generate SQL ──────────────────────────────────────────────────
    sql = _gen_sql(model_name, requirement, openai_client)
    logger.info(f"[{ticket_identifier}] SQL generated ({len(sql)} chars)")

    # ── Step 2: Validate + auto-fix loop (max 2 retries) ─────────────────────
    validation_log = []
    for attempt in range(3):
        valid, explain_error = _validate_syntax(sql, db)
        if not valid:
            issues = [f"SQL syntax/schema error from Postgres EXPLAIN: {explain_error}"]
        else:
            issues = _self_review(sql, requirement, openai_client)

        if not issues:
            logger.info(f"[{ticket_identifier}] Validation passed (attempt {attempt + 1})")
            break

        logger.info(f"[{ticket_identifier}] Validation issues (attempt {attempt + 1}): {issues}")
        validation_log.append({"attempt": attempt + 1, "issues": issues})

        if attempt < 2:
            sql = _fix_sql(sql, requirement, issues, openai_client)
            logger.info(f"[{ticket_identifier}] SQL auto-fixed, retrying validation")
    else:
        # All 3 attempts exhausted — still push, but flag in PR body
        logger.warning(f"[{ticket_identifier}] Validation did not fully pass after 3 attempts")

    validation_status = (
        "✅ SQL validated (EXPLAIN + self-review passed)"
        if not validation_log
        else f"⚠️ Auto-fixed {len(validation_log)} issue(s) before push — review carefully"
    )

    # ── Step 3: Generate YAML from the validated SQL ──────────────────────────
    yml = _gen_yml(model_name, requirement, sql, openai_client)

    # ── Step 4: Push to GitHub ────────────────────────────────────────────────
    github.create_branch(branch)
    github.push_file(
        path=f"models/gold/{model_name}.sql",
        content=sql,
        branch=branch,
        commit_msg=f"feat: add {model_name} [auto, {ticket_identifier}]",
    )
    github.push_file(
        path=f"models/gold/_auto_{model_name}.yml",
        content=f"version: 2\n\nmodels:\n  {yml}\n",
        branch=branch,
        commit_msg=f"docs: schema for {model_name} [auto, {ticket_identifier}]",
    )

    issues_summary = ""
    if validation_log:
        issues_summary = "\n\n### Auto-fix log\n" + "\n".join(
            f"**Attempt {e['attempt']}:** " + "; ".join(e["issues"])
            for e in validation_log
        )

    pr = github.open_pr(
        title=f"feat: {model_name} [{ticket_identifier}]",
        body=f"""## Auto-generated dbt model

**Linear**: {ticket_identifier}
**Requirement**: {requirement}

### Validation
{validation_status}{issues_summary}

### Generated SQL
```sql
{sql[:1500]}{'...' if len(sql) > 1500 else ''}
```

### Review checklist
- [ ] SQL logic matches the requirement
- [ ] Column names and formulas are correct
- [ ] Tests are sufficient
- [ ] Merge when ready — GitHub Actions will run dbt automatically

> 🤖 Generated by GetSafe Analytics Agent""",
        branch=branch,
    )

    return {
        "success": True,
        "model_name": model_name,
        "branch": branch,
        "pr_url": pr["html_url"],
        "pr_number": pr["number"],
        "sql_preview": sql[:600],
        "validation_passed": not validation_log,
    }
