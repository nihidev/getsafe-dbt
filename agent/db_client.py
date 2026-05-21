import logging

import psycopg2
import psycopg2.extras
from psycopg2 import pool
from typing import Any

logger = logging.getLogger(__name__)


class DatabaseClient:
    def __init__(self, host: str, port: int, dbname: str, user: str, password: str):
        self._params = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
            "sslmode": "require",
            "connect_timeout": 10,
        }
        self._pool = pool.ThreadedConnectionPool(minconn=1, maxconn=5, **self._params)

    def _get(self):
        return self._pool.getconn()

    def _put(self, conn):
        self._pool.putconn(conn)

    def explain_sql(self, sql: str) -> dict[str, Any]:
        conn = self._get()
        try:
            with conn.cursor() as cur:
                cur.execute(f"EXPLAIN {sql}")
            return {"valid": True}
        except psycopg2.Error as e:
            conn.rollback()
            return {"valid": False, "error": str(e)}
        finally:
            self._put(conn)

    def table_exists(self, schema: str, table: str) -> bool:
        result = self.query_safe(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            (schema, table),
            limit=1,
        )
        return bool(result.get("rows"))

    def query(self, sql: str, limit: int = 100) -> dict[str, Any]:
        """Unparameterised SELECT — use only for hardcoded/trusted SQL."""
        stripped = sql.strip().upper()
        if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
            return {"error": "Only SELECT / WITH queries are allowed"}

        if "LIMIT" not in stripped:
            sql = f"{sql.rstrip(';')} LIMIT {limit}"

        conn = self._get()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                return {
                    "columns": columns,
                    "rows": [dict(row) for row in rows],
                    "row_count": len(rows),
                }
        except psycopg2.Error as e:
            conn.rollback()
            return {"error": str(e)}
        finally:
            self._put(conn)

    def query_safe(self, sql: str, params: tuple = (), limit: int = 100) -> dict[str, Any]:
        """Parameterised SELECT — use for any values derived from user or LLM input."""
        stripped = sql.strip().upper()
        if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
            return {"error": "Only SELECT / WITH queries are allowed"}

        if limit and "LIMIT" not in stripped:
            sql = f"{sql.rstrip(';')} LIMIT {limit}"

        conn = self._get()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                return {
                    "columns": columns,
                    "rows": [dict(row) for row in rows],
                    "row_count": len(rows),
                }
        except psycopg2.Error as e:
            conn.rollback()
            return {"error": str(e)}
        finally:
            self._put(conn)

    # ── Tracked PRs (agent state persistence) ─────────────────────────────────

    def ensure_tracked_prs_table(self) -> None:
        conn = self._get()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS public.agent_tracked_prs (
                        pr_number         INTEGER PRIMARY KEY,
                        model_name        TEXT NOT NULL,
                        ticket_identifier TEXT NOT NULL,
                        issue_id          TEXT NOT NULL,
                        label_ids         TEXT[] NOT NULL DEFAULT '{}',
                        created_at        TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"Could not create agent_tracked_prs table: {e}")
        finally:
            self._put(conn)

    def upsert_tracked_pr(self, pr_number: int, model_name: str,
                          ticket_identifier: str, issue_id: str, label_ids: list) -> None:
        conn = self._get()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.agent_tracked_prs
                        (pr_number, model_name, ticket_identifier, issue_id, label_ids)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (pr_number) DO UPDATE SET
                        model_name        = EXCLUDED.model_name,
                        ticket_identifier = EXCLUDED.ticket_identifier,
                        issue_id          = EXCLUDED.issue_id,
                        label_ids         = EXCLUDED.label_ids
                    """,
                    (pr_number, model_name, ticket_identifier, issue_id, label_ids),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"Failed to persist tracked PR #{pr_number}: {e}")
        finally:
            self._put(conn)

    def delete_tracked_pr(self, pr_number: int) -> None:
        conn = self._get()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM public.agent_tracked_prs WHERE pr_number = %s",
                    (pr_number,),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"Failed to delete tracked PR #{pr_number}: {e}")
        finally:
            self._put(conn)

    def load_tracked_prs(self) -> dict[int, dict]:
        conn = self._get()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM public.agent_tracked_prs")
                rows = cur.fetchall()
                return {
                    row["pr_number"]: {
                        "model_name":        row["model_name"],
                        "ticket_identifier": row["ticket_identifier"],
                        "issue_id":          row["issue_id"],
                        "label_ids":         list(row["label_ids"] or []),
                    }
                    for row in rows
                }
        except Exception as e:
            logger.warning(f"Failed to load tracked PRs from Supabase: {e}")
            return {}
        finally:
            self._put(conn)
