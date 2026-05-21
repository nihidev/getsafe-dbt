import requests
from typing import Optional


class MetabaseClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._db_id: Optional[int] = None

    # ── auth — API key is sent on every request, no session management needed ──

    def _headers(self) -> dict:
        return {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
        }

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _get(self, path: str) -> dict | list:
        resp = requests.get(f"{self.base_url}{path}", headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        resp = requests.post(f"{self.base_url}{path}", json=body, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, body: dict) -> dict:
        resp = requests.put(f"{self.base_url}{path}", json=body, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    # ── database discovery ────────────────────────────────────────────────────

    def get_database_id(self) -> int:
        if self._db_id:
            return self._db_id
        data = self._get("/api/database")
        databases = data.get("data", data) if isinstance(data, dict) else data
        for db in databases:
            if db.get("engine") in ("postgres", "postgresql"):
                self._db_id = db["id"]
                return self._db_id
        self._db_id = databases[0]["id"]
        return self._db_id

    # ── questions ─────────────────────────────────────────────────────────────

    def create_question(
        self,
        name: str,
        sql: str,
        display: str,
        database_id: int,
        collection_id: Optional[int] = None,
    ) -> dict:
        payload: dict = {
            "name": name,
            "display": display,
            "dataset_query": {
                "type": "native",
                "native": {"query": sql},
                "database": database_id,
            },
            "visualization_settings": {},
        }
        if collection_id:
            payload["collection_id"] = collection_id
        return self._post("/api/card", payload)

    def list_questions(self) -> list:
        data = self._get("/api/card")
        return data if isinstance(data, list) else data.get("data", [])

    # ── dashboards ────────────────────────────────────────────────────────────

    def create_dashboard(self, name: str, description: str = "") -> dict:
        return self._post("/api/dashboard", {"name": name, "description": description})

    def add_card_to_dashboard(
        self,
        dashboard_id: int,
        card_id: int,
        row: int = 0,
        col: int = 0,
        size_x: int = 12,
        size_y: int = 8,
    ) -> dict:
        # Metabase 0.46+ uses PUT /api/dashboard/:id with full dashcards payload
        existing = self._get(f"/api/dashboard/{dashboard_id}")
        current_cards = existing.get("dashcards", [])

        new_card = {
            "id": -(len(current_cards) + 1),  # negative id = new card
            "card_id": card_id,
            "row": row,
            "col": col,
            "size_x": size_x,
            "size_y": size_y,
            "series": [],
            "parameter_mappings": [],
            "visualization_settings": {},
        }
        return self._put(
            f"/api/dashboard/{dashboard_id}",
            {"dashcards": current_cards + [new_card]},
        )

    def list_dashboards(self) -> list:
        data = self._get("/api/dashboard")
        return data if isinstance(data, list) else data.get("data", [])
