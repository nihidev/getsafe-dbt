import logging
import os

logger = logging.getLogger(__name__)

GOLD = os.environ.get("GOLD_SCHEMA", "public_gold")
MB_PUBLIC = os.environ.get("METABASE_PUBLIC_URL", "http://localhost:12345")

# Linear label IDs (constant)
LABEL_AUTO_DONE = "bce129d2-d698-4ea0-a384-5192a3ea7481"


def _default_viz(model_name: str) -> tuple[str, str]:
    """Pick a sensible default chart SQL + display type for known model patterns."""
    if "hhi" in model_name or "concentration" in model_name:
        return (
            f"SELECT month, hhi_score, concentration_level, active_parties\n"
            f"FROM {GOLD}.{model_name}\nORDER BY month",
            "line",
        )
    if "retention" in model_name or "cohort" in model_name:
        return (
            f"SELECT * FROM {GOLD}.{model_name} LIMIT 500",
            "table",
        )
    if "premium" in model_name and "party" in model_name:
        return (
            f"SELECT month, party, market_share_pct FROM {GOLD}.{model_name} ORDER BY month, party",
            "bar",
        )
    if "clv" in model_name or "lifetime" in model_name:
        return (
            f"SELECT user_id, product_group, clv_tier, lifetime_value_eur\n"
            f"FROM {GOLD}.{model_name} ORDER BY lifetime_value_eur DESC",
            "bar",
        )
    return (
        f"SELECT * FROM {GOLD}.{model_name} LIMIT 200",
        "table",
    )


def run(
    model_name: str,
    ticket_identifier: str,
    issue_id: str,
    label_ids: list,
    db,
    metabase,
    linear,
) -> dict:
    """
    Post-merge workflow. Called when the agent detects a new_model PR was merged.

    Flow:
      1. Verify the table exists in Supabase (dbt must have run via GitHub Actions first)
      2. Create a Metabase question + dashboard for the new model
      3. Post a completion comment on the Linear ticket and move to Done
    """
    # Step 1: Table existence check — if dbt hasn't run yet, defer to next poll cycle
    if not db.table_exists(GOLD, model_name):
        logger.info(
            f"[{ticket_identifier}] PR merged but {GOLD}.{model_name} not yet materialized — "
            "will retry next cycle"
        )
        return {"ready": False, "reason": "table_not_yet_materialized"}

    logger.info(f"[{ticket_identifier}] Table {GOLD}.{model_name} confirmed — building dashboard")

    # Step 2: Create Metabase question + dashboard
    viz_sql, display = _default_viz(model_name)
    db_id = metabase.get_database_id()

    human_name = model_name.replace("_", " ").title()

    card = metabase.create_question(
        name=f"{human_name} [{ticket_identifier}]",
        sql=viz_sql,
        display=display,
        database_id=db_id,
    )

    dash = metabase.create_dashboard(
        name=f"{human_name} — {ticket_identifier}",
        description=f"Auto-generated after merge of {ticket_identifier}",
    )

    metabase.add_card_to_dashboard(
        dashboard_id=dash["id"],
        card_id=card["id"],
    )

    question_url = f"{MB_PUBLIC}/question/{card['id']}"
    dashboard_url = f"{MB_PUBLIC}/dashboard/{dash['id']}"

    logger.info(f"[{ticket_identifier}] Dashboard created: {dashboard_url}")

    # Step 3: Notify Linear, add auto-done label, move to Done
    comment = f"""## ✅ Deployment Complete

**Model:** `{model_name}`
**Table:** `{GOLD}.{model_name}`

📊 **Dashboard** → {dashboard_url}
📈 **Question** → {question_url}

dbt model is materialized in Supabase and the Metabase dashboard is ready.

> 🤖 GetSafe Analytics Agent · post-merge · `{ticket_identifier}`"""

    linear.comment(issue_id, comment)
    linear.add_label(issue_id, LABEL_AUTO_DONE, label_ids)
    linear.move_to_done(issue_id)

    logger.info(f"[{ticket_identifier}] Post-merge workflow complete ✓")

    return {
        "ready": True,
        "dashboard_url": dashboard_url,
        "question_url": question_url,
        "model_name": model_name,
    }
