import asyncio
import json
import logging
import traceback

from linear_client import LABEL_AUTO_DONE, LABEL_AUTO_ERROR

logger = logging.getLogger(__name__)

# In-memory registry of open new_model PRs waiting for merge
# { pr_number: {model_name, ticket_identifier, issue_id, label_ids} }
_tracked_prs: dict[int, dict] = {}


# ── comment formatters ────────────────────────────────────────────────────────

def _dashboard_comment(r: dict, intent: dict, tid: str) -> str:
    return f"""## ✅ Dashboard Created

📊 **Dashboard** → {r['dashboard_url']}
📈 **Question** → {r['question_url']}

**SQL:**
```sql
{r['sql']}
```
**Rows returned:** {r['row_count']}

> 🤖 GetSafe Analytics Agent · `{tid}`"""


def _quality_comment(r: dict, intent: dict, tid: str) -> str:
    icon = "✅" if r["success"] else "⚠️"
    passed = "\n".join(r["passed"]) or "_none_"
    failed = "\n".join(r["failed"]) or "_none_"
    return f"""## {icon} Data Quality Report — `{r['table']}`

**Checks passed:** {r['checks_passed']} &nbsp; **Failed:** {r['checks_failed']}

### Passed
{passed}

### Failed
{failed}

> 🤖 GetSafe Analytics Agent · `{tid}`"""


def _explore_comment(r: dict, intent: dict, tid: str) -> str:
    sample = ""
    if r.get("sample_rows"):
        sample = f"\n\n**Sample ({r['row_count']} rows):**\n```json\n{json.dumps(r['sample_rows'][:3], default=str, indent=2)}\n```"
    return f"""## 🔍 Data Exploration

{r['summary']}
{sample}

**SQL:**
```sql
{r['sql']}
```

> 🤖 GetSafe Analytics Agent · `{tid}`"""


def _model_comment(r: dict, intent: dict, tid: str) -> str:
    validation = "✅ Validated" if r.get("validation_passed") else "⚠️ Auto-fixed (check PR)"
    return f"""## 🛠️ dbt Model Ready — PR Open

**Model:** `{r['model_name']}`
**PR:** {r['pr_url']}
**Branch:** `{r['branch']}`
**Validation:** {validation}

**SQL preview:**
```sql
{r['sql_preview']}
```

Review and merge the PR — dbt will run automatically via GitHub Actions,
then this ticket will be updated with the Metabase dashboard link.

> 🤖 GetSafe Analytics Agent · `{tid}`"""


def _error_comment(error: str, tid: str) -> str:
    return f"""## ❌ Agent Error

The automation agent encountered an error on this ticket.

```
{error[:800]}
```

Please review and handle manually, or update the ticket description and set back to Todo.

> 🤖 GetSafe Analytics Agent · `{tid}`"""


# ── core processor ────────────────────────────────────────────────────────────

async def process_ticket(ticket: dict, linear, db, metabase, github, openai_client):
    from intent_classifier import classify
    import workflows.dashboard as dash_wf
    import workflows.quality   as qual_wf
    import workflows.explore   as expl_wf
    import workflows.model     as model_wf

    issue_id   = ticket["id"]
    identifier = ticket["identifier"]
    title      = ticket["title"]
    desc       = ticket.get("description") or ""
    label_ids  = ticket.get("labelIds") or []

    logger.info(f"[{identifier}] Processing: {title}")
    linear.move_to_in_progress(issue_id)

    try:
        intent      = classify(title, desc)
        intent_type = intent.get("intent", "explore")
        logger.info(f"[{identifier}] Intent → {intent_type}")

        if intent_type == "dashboard":
            result  = dash_wf.run(intent, db, metabase)
            comment = _dashboard_comment(result, intent, identifier)

        elif intent_type == "data_quality":
            result  = qual_wf.run(intent, db)
            comment = _quality_comment(result, intent, identifier)

        elif intent_type == "new_model":
            # Pass db so the workflow can validate SQL before pushing
            result  = model_wf.run(intent, github, db, identifier, openai_client)
            comment = _model_comment(result, intent, identifier)
            # Track the PR so we can detect when it's merged
            if result.get("success") and result.get("pr_number"):
                _tracked_prs[result["pr_number"]] = {
                    "model_name":        result["model_name"],
                    "ticket_identifier": identifier,
                    "issue_id":          issue_id,
                    "label_ids":         label_ids,
                }
                logger.info(
                    f"[{identifier}] Tracking PR #{result['pr_number']} for post-merge"
                )

        else:
            result  = expl_wf.run(intent, db, openai_client)
            comment = _explore_comment(result, intent, identifier)

        linear.comment(issue_id, comment)
        linear.add_label(issue_id, LABEL_AUTO_DONE, label_ids)

        # new_model stays In Progress (waiting for PR review + dbt run); rest → Done
        if intent_type != "new_model":
            linear.move_to_done(issue_id)

        logger.info(f"[{identifier}] Done ✓")

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error(f"[{identifier}] Error:\n{tb}")
        linear.comment(issue_id, _error_comment(str(exc), identifier))
        linear.add_label(issue_id, LABEL_AUTO_ERROR, label_ids)


# ── post-merge PR tracker ─────────────────────────────────────────────────────

async def _check_merged_prs(linear, db, metabase, github):
    """
    Called each polling cycle. For every tracked new_model PR, check if it was
    merged. If yes, run the post-merge workflow (Metabase + Linear completion).
    """
    import workflows.post_merge as post_merge_wf

    completed = []
    for pr_number, info in list(_tracked_prs.items()):
        try:
            pr_data = github.get_pr(pr_number)
            if not pr_data.get("merged_at"):
                continue  # still open or closed without merge

            logger.info(
                f"[{info['ticket_identifier']}] PR #{pr_number} merged — "
                "running post-merge workflow"
            )
            result = post_merge_wf.run(
                model_name=info["model_name"],
                ticket_identifier=info["ticket_identifier"],
                issue_id=info["issue_id"],
                label_ids=info["label_ids"],
                db=db,
                metabase=metabase,
                linear=linear,
            )
            if result.get("ready"):
                completed.append(pr_number)
            # If not ready (table not materialized yet), leave in tracking dict
            # and retry next polling cycle

        except Exception as exc:
            logger.error(f"PR tracking error for PR #{pr_number}: {exc}")

    for n in completed:
        del _tracked_prs[n]


# ── polling loop ──────────────────────────────────────────────────────────────

async def start_polling(interval: int, linear, db, metabase, github, openai_client):
    logger.info(f"Polling loop started (interval: {interval}s)")
    while True:
        try:
            # Check for new tickets
            tickets = linear.get_pending_tickets()
            if tickets:
                logger.info(f"Found {len(tickets)} pending ticket(s)")
                for t in tickets:
                    await process_ticket(t, linear, db, metabase, github, openai_client)
            else:
                logger.debug("No pending tickets")

            # Check for merged new_model PRs
            if _tracked_prs:
                await _check_merged_prs(linear, db, metabase, github)

        except Exception as exc:
            logger.error(f"Polling error: {exc}")
        await asyncio.sleep(interval)
