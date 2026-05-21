import json
import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

VALID_INTENTS = {"dashboard", "data_quality", "new_model", "explore"}

_SYSTEM = """You are an intent classifier for a data analytics automation system.

Available gold tables:
- gold_fct_monthly_premiums       → party, month, written_premium, net_premium, refunded_premium, earned_premium, transaction_count
- gold_fct_accounting_reconciliation → party, month, accounting_premium, finance_premium, delta, delta_pct, reconciliation_status
- gold_fct_customer_activity_daily  → user_id, activity_date, product_group, daily_premium, monthly_premium, churned_at

Classify the Linear ticket into exactly one of:
  dashboard    – user wants a Metabase chart or dashboard
  data_quality – user wants a data quality audit / dbt test results
  new_model    – user needs a new dbt SQL model built
  explore      – user has a data question, wants a plain-English answer

Return valid JSON only — no markdown, no explanation. Schema:
{
  "intent":      "dashboard|data_quality|new_model|explore",
  "table":       "gold_fct_monthly_premiums|gold_fct_accounting_reconciliation|gold_fct_customer_activity_daily|null",
  "chart_type":  "bar|line|pie|table|scalar|area|null",
  "filters":     {"party": "...", "month": "...", ...},
  "metric":      "short description of what the user wants",
  "model_name":  "snake_case name for new_model intent, else null",
  "reasoning":   "one sentence explaining your classification"
}"""


def classify(title: str, description: str = "") -> dict:
    content = f"Title: {title}\nDescription: {description or '(none)'}"
    resp = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": content},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    result = json.loads(resp.choices[0].message.content)

    if result.get("intent") not in VALID_INTENTS:
        logger.warning(
            f"Classifier returned invalid intent '{result.get('intent')}' — defaulting to 'explore'"
        )
        result["intent"] = "explore"

    return result
