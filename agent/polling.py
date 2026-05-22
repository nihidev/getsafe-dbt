"""
Ticket processor and PR tracker.

Polling has been removed — tickets are now triggered by N8N webhook → /process-ticket.
PR merge detection is triggered by N8N/GitHub webhook → /check-prs.
"""
import json
import logging
import traceback

from linear_client import LABEL_AUTO_DONE, LABEL_AUTO_ERROR

logger = logging.getLogger(__name__)

# In-memory cache of open new_model PRs awaiting merge.
# Populated from Supabase at startup (see init_tracked_prs) and kept in sync on every change.
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


# ── startup init ──────────────────────────────────────────────────────────────

def init_tracked_prs(db) -> None:
    """Load persisted tracked PRs from Supabase into the in-memory cache at startup."""
    loaded = db.load_tracked_prs()
    _tracked_prs.update(loaded)
    if loaded:
        logger.info(f"Loaded {len(loaded)} tracked PR(s) from Supabase: {list(loaded.keys())}")


# ── core ticket processor ─────────────────────────────────────────────────────

async def process_ticket(ticket: dict, linear, db, metabase, github, openai_client):
    import workflows.dashboard as dash_wf
    import workflows.quality   as qual_wf
    import workflows.explore   as expl_wf
    import workflows.model     as model_wf
    from intent_classifier import classify

    issue_id   = ticket["id"]
    identifier = ticket["identifier"]
    title      = ticket["title"]
    desc       = ticket.get("description") or ""
    label_ids  = ticket.get("labelIds") or []

    # Idempotency guard — skip tickets already handled by a previous run
    if LABEL_AUTO_DONE in label_ids or LABEL_AUTO_ERROR in label_ids:
        logger.info(f"[{identifier}] Already processed — skipping")
        return

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
            # Inject full ticket text so _gen_sql has the complete requirement,
            # not just the classifier's short metric summary.
            intent["_title"] = title
            intent["_description"] = desc
            result  = model_wf.run(intent, github, db, identifier, openai_client)
            comment = _model_comment(result, intent, identifier)

            if result.get("success") and result.get("pr_number"):
                info = {
                    "model_name":        result["model_name"],
                    "ticket_identifier": identifier,
                    "issue_id":          issue_id,
                    "label_ids":         label_ids,
                }
                _tracked_prs[result["pr_number"]] = info
                db.upsert_tracked_pr(pr_number=result["pr_number"], **info)
                logger.info(f"[{identifier}] Tracking PR #{result['pr_number']}")

        else:
            result  = expl_wf.run(intent, db, openai_client)
            comment = _explore_comment(result, intent, identifier)

        linear.comment(issue_id, comment)
        linear.add_label(issue_id, LABEL_AUTO_DONE, label_ids)

        # new_model stays In Progress (waiting for PR review); everything else → Done
        if intent_type != "new_model":
            linear.move_to_done(issue_id)

        logger.info(f"[{identifier}] Done ✓")

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error(f"[{identifier}] Error:\n{tb}")
        linear.comment(issue_id, _error_comment(str(exc), identifier))
        linear.add_label(issue_id, LABEL_AUTO_ERROR, label_ids)


# ── PR merge checker (called via /check-prs endpoint) ────────────────────────

async def check_merged_prs(linear, db, metabase, github) -> dict:
    """
    Check whether any tracked new_model PRs have been merged.
    Called by N8N on a schedule or triggered by a GitHub PR-merged webhook.
    Returns a summary dict for the API response.
    """
    import workflows.post_merge as post_merge_wf

    if not _tracked_prs:
        return {"checked": 0, "completed": [], "pending": []}

    completed = []
    pending = []

    for pr_number, info in list(_tracked_prs.items()):
        try:
            pr_data = github.get_pr(pr_number)
            if not pr_data.get("merged_at"):
                pending.append(pr_number)
                continue

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
                _tracked_prs.pop(pr_number, None)
                db.delete_tracked_pr(pr_number)
            else:
                # Table not yet materialized — retry on next call
                pending.append(pr_number)

        except Exception as exc:
            logger.error(f"PR tracking error for PR #{pr_number}: {exc}")
            pending.append(pr_number)

    return {
        "checked": len(completed) + len(pending),
        "completed": completed,
        "pending": pending,
    }
