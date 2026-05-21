import os
import time

import requests
import streamlit as st

AGENT_URL = os.environ.get("AGENT_URL", "http://agent:8000")
METABASE_PUBLIC_URL = os.environ.get("METABASE_PUBLIC_URL", "http://localhost:12345")
LINEAR_TEAM_URL = "https://linear.app/getsafe/team/GET/issues"

st.set_page_config(
    page_title="GetSafe Analytics Agent",
    page_icon="📊",
    layout="wide",
)

st.title("📊 GetSafe Analytics Agent")

tab_chat, tab_linear = st.tabs(["💬 Chat", "🎫 Linear Ticket Processor"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Chat
# ══════════════════════════════════════════════════════════════════════════════
with tab_chat:
    st.caption("Describe what you want to see — the agent writes the SQL and builds it in Metabase.")

    with st.sidebar:
        st.header("Quick examples")
        examples = [
            "Show monthly premiums by party as a bar chart",
            "Create a line chart of net premium over time for berlinre",
            "Show reconciliation status for all parties as a table",
            "How many active customers per product group?",
            "Run a data quality check on the monthly premiums table",
            "Build a Finance Overview dashboard with monthly and reconciliation charts",
        ]
        for ex in examples:
            if st.button(ex, use_container_width=True, key=f"ex_{ex[:20]}"):
                st.session_state["prefill"] = ex

        st.divider()
        st.markdown(f"[Open Metabase ↗]({METABASE_PUBLIC_URL})")
        st.markdown(f"[Open Linear ↗]({LINEAR_TEAM_URL})")

        if st.button("Clear conversation", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("actions"):
                with st.expander(f"Agent actions ({len(msg['actions'])})"):
                    for action in msg["actions"]:
                        st.code(action, language="python")

    prefill = st.session_state.pop("prefill", "")
    prompt = st.chat_input("e.g. Show monthly premiums by party as a bar chart") or prefill

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Agent is working…"):
                try:
                    resp = requests.post(
                        f"{AGENT_URL}/chat",
                        json={"messages": [
                            {"role": m["role"], "content": m["content"]}
                            for m in st.session_state.messages
                        ]},
                        timeout=120,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    reply = data["response"]
                    actions = data.get("actions_taken", [])
                    st.markdown(reply)
                    if actions:
                        with st.expander(f"Agent actions ({len(actions)})"):
                            for a in actions:
                                st.code(a, language="python")
                    if any("question" in a or "dashboard" in a for a in actions):
                        st.success(f"Created in Metabase → [Open Metabase]({METABASE_PUBLIC_URL})")
                except requests.exceptions.ConnectionError:
                    reply, actions = "Cannot reach the agent service. Is Docker running?", []
                    st.error(reply)
                except Exception as exc:
                    reply, actions = f"Error: {exc}", []
                    st.error(reply)

        st.session_state.messages.append({"role": "assistant", "content": reply, "actions": actions})


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Linear Ticket Processor
# ══════════════════════════════════════════════════════════════════════════════
with tab_linear:
    st.caption("Process a Linear ticket manually, or check for merged new-model PRs.")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Process a specific ticket")
        st.markdown("""
Create a ticket in **Linear → GetSafe team** with:
- Label: `analytics-request`
- Additional label: `dashboard`, `data-quality`, `new-model`, or `explore`
- Title: your request in plain English

Tickets are processed automatically when created (via N8N webhook).
Use the form below to force-process a ticket immediately.
""")
        ticket_id = st.text_input("Ticket identifier", placeholder="GET-1", key="ticket_input")
        if st.button("▶ Process ticket now", type="primary", disabled=not ticket_id):
            with st.spinner(f"Processing {ticket_id}…"):
                try:
                    resp = requests.post(
                        f"{AGENT_URL}/process-ticket",
                        json={"ticket_identifier": ticket_id},
                        timeout=120,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("success"):
                        st.success(f"✅ {ticket_id} processed successfully!")
                        st.info("Check the ticket in Linear for the agent's comment and result link.")
                        st.markdown(f"[Open Linear ticket ↗]({LINEAR_TEAM_URL})")
                    else:
                        st.error(f"❌ {data.get('error', 'Unknown error')}")
                except Exception as exc:
                    st.error(f"Error: {exc}")

    with col2:
        st.subheader("Post-merge check")
        st.markdown("""
After a `new-model` PR is merged and dbt runs:

1. GitHub Actions materialises the table in Supabase
2. Click **Check PRs** to build the Metabase dashboard and close the ticket

This is also called automatically by N8N when a PR is merged.
""")
        if st.button("🔍 Check merged PRs", use_container_width=True, type="primary"):
            with st.spinner("Checking for merged new-model PRs…"):
                try:
                    resp = requests.get(f"{AGENT_URL}/check-prs", timeout=60)
                    resp.raise_for_status()
                    data = resp.json()
                    checked = data.get("checked", 0)
                    completed = data.get("completed", [])
                    pending = data.get("pending", [])
                    if not checked:
                        st.info("No tracked PRs to check.")
                    else:
                        if completed:
                            st.success(f"✅ Completed {len(completed)} PR(s): {completed}")
                        if pending:
                            st.info(f"⏳ {len(pending)} PR(s) still pending (table not yet materialized): {pending}")
                except Exception as exc:
                    st.error(f"Error: {exc}")

        st.divider()
        st.markdown("**Label reference:**")
        labels = {
            "🔵 analytics-request": "Main trigger (N8N watches this)",
            "🟣 dashboard": "Metabase chart",
            "🟠 data-quality": "Quality audit",
            "🟢 new-model": "dbt PR",
            "🩵 explore": "Plain-English answer",
            "✅ auto-done": "Agent succeeded",
            "🔴 auto-error": "Agent failed",
        }
        for label, desc in labels.items():
            st.markdown(f"- **{label}** — {desc}")
