import logging
from typing import Optional

import requests

GRAPHQL_URL = "https://api.linear.app/graphql"

logger = logging.getLogger(__name__)

# GetSafe team state IDs
STATE_TODO        = "5e06c58c-202c-473c-bd40-5b4f30ae380d"
STATE_IN_PROGRESS = "197cb2a9-44c9-4d87-a814-507d541c428a"
STATE_DONE        = "655c61b5-33d0-4208-a508-de3220181e07"

# GetSafe label IDs
LABEL_AUTO_DONE  = "bce129d2-d698-4ea0-a384-5192a3ea7481"
LABEL_AUTO_ERROR = "e833d33c-a36d-4167-af28-0e42bb8d7dc1"


class LinearClient:
    def __init__(self, api_key: str, team_id: str):
        self.team_id = team_id
        self._headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }

    def _query(self, query: str, variables: dict | None = None) -> dict:
        resp = requests.post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"Linear GraphQL error: {data['errors']}")
        return data["data"]

    # ── ticket reads ──────────────────────────────────────────────────────────

    def get_pending_tickets(self) -> list[dict]:
        """Return all Todo + analytics-request tickets in the GetSafe team."""
        query = """
        query($teamId: String!) {
            team(id: $teamId) {
                issues(
                    filter: { state: { type: { in: ["unstarted", "backlog"] } } }
                    first: 20
                ) {
                    nodes {
                        id
                        identifier
                        title
                        description
                        labelIds
                        labels { nodes { id name } }
                        state { id name type }
                    }
                }
            }
        }
        """
        data = self._query(query, {"teamId": self.team_id})
        all_issues = data["team"]["issues"]["nodes"]
        # Filter in Python for analytics-request label
        return [
            i for i in all_issues
            if any(l["name"] == "analytics-request" for l in i["labels"]["nodes"])
        ]

    def get_ticket(self, identifier: str) -> Optional[dict]:
        """Fetch a single ticket by identifier e.g. GET-12."""
        query = """
        query($id: String!) {
            issue(id: $id) {
                id identifier title description labelIds
                labels { nodes { id name } }
                state { id name type }
            }
        }
        """
        try:
            data = self._query(query, {"id": identifier})
            return data["issue"]
        except RuntimeError:
            # GraphQL error — ticket not found
            return None
        # Network / HTTP errors propagate so callers see the real failure

    # ── state transitions ─────────────────────────────────────────────────────

    def move_to_in_progress(self, issue_id: str):
        self._set_state(issue_id, STATE_IN_PROGRESS)

    def move_to_done(self, issue_id: str):
        self._set_state(issue_id, STATE_DONE)

    def _set_state(self, issue_id: str, state_id: str):
        mutation = """
        mutation($id: String!, $stateId: String!) {
            issueUpdate(id: $id, input: { stateId: $stateId }) {
                success
            }
        }
        """
        self._query(mutation, {"id": issue_id, "stateId": state_id})

    # ── labels ────────────────────────────────────────────────────────────────

    def add_label(self, issue_id: str, label_id: str, current_label_ids: list[str]):
        """Add a label without removing existing ones."""
        if label_id in current_label_ids:
            return
        new_ids = list(set(current_label_ids + [label_id]))
        mutation = """
        mutation($id: String!, $labelIds: [String!]!) {
            issueUpdate(id: $id, input: { labelIds: $labelIds }) {
                success
            }
        }
        """
        self._query(mutation, {"id": issue_id, "labelIds": new_ids})

    # ── comments ──────────────────────────────────────────────────────────────

    def comment(self, issue_id: str, body: str):
        mutation = """
        mutation($issueId: String!, $body: String!) {
            commentCreate(input: { issueId: $issueId, body: $body }) {
                success
            }
        }
        """
        self._query(mutation, {"issueId": issue_id, "body": body})
