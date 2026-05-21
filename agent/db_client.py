import psycopg2
import psycopg2.extras
from typing import Any


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

    def explain_sql(self, sql: str) -> dict[str, Any]:
        """Run EXPLAIN to validate SQL syntax and schema references without writing data."""
        conn = psycopg2.connect(**self._params)
        try:
            with conn.cursor() as cur:
                cur.execute(f"EXPLAIN {sql}")
            return {"valid": True}
        except psycopg2.Error as e:
            return {"valid": False, "error": str(e)}
        finally:
            conn.close()

    def table_exists(self, schema: str, table: str) -> bool:
        result = self.query(
            f"SELECT 1 FROM information_schema.tables "
            f"WHERE table_schema = '{schema}' AND table_name = '{table}'",
            limit=1,
        )
        return bool(result.get("rows"))

    def query(self, sql: str, limit: int = 100) -> dict[str, Any]:
        stripped = sql.strip().upper()
        if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
            return {"error": "Only SELECT / WITH queries are allowed"}

        if "LIMIT" not in stripped:
            sql = f"{sql.rstrip(';')} LIMIT {limit}"

        conn = psycopg2.connect(**self._params)
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
        finally:
            conn.close()
