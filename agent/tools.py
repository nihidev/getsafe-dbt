TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_sql_query",
            "description": (
                "Run a SQL SELECT query against Supabase and return results as JSON. "
                "Always do this first to validate data before creating a Metabase question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SQL SELECT query. Always prefix tables with the gold schema, e.g. public_gold.gold_fct_monthly_premiums"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows to return (default 100)",
                        "default": 100
                    }
                },
                "required": ["sql"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_metabase_question",
            "description": "Create a saved question/chart in Metabase using a SQL query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Display name for the question in Metabase"
                    },
                    "sql": {
                        "type": "string",
                        "description": "SQL query for the question (with schema prefix)"
                    },
                    "display": {
                        "type": "string",
                        "enum": ["table", "bar", "line", "pie", "scalar", "area", "row"],
                        "description": "Chart type: bar/line/area for trends, pie for proportions, scalar for a single KPI, table for raw data"
                    },
                    "collection_id": {
                        "type": "integer",
                        "description": "Optional Metabase collection ID to organise the question"
                    }
                },
                "required": ["name", "sql", "display"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_metabase_dashboard",
            "description": "Create a new empty dashboard in Metabase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Dashboard name"},
                    "description": {"type": "string", "description": "Optional description"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_question_to_dashboard",
            "description": "Pin an existing Metabase question/card onto a dashboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "integer"},
                    "card_id": {"type": "integer"},
                    "row": {"type": "integer", "default": 0},
                    "col": {"type": "integer", "default": 0},
                    "size_x": {"type": "integer", "default": 12, "description": "Width in grid units (max 24)"},
                    "size_y": {"type": "integer", "default": 8, "description": "Height in grid units"}
                },
                "required": ["dashboard_id", "card_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_metabase_questions",
            "description": "List existing saved questions in Metabase (up to 20).",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_metabase_dashboards",
            "description": "List existing dashboards in Metabase (up to 20).",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_data_quality",
            "description": (
                "Run a full suite of data quality checks on a gold layer table — equivalent to dbt tests. "
                "Checks: row count, null values on required columns, grain uniqueness, accepted values, "
                "and a business summary. Use this to audit dbt output or investigate data issues."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "enum": [
                            "gold_fct_monthly_premiums",
                            "gold_fct_accounting_reconciliation",
                            "gold_fct_customer_activity_daily",
                        ],
                        "description": "Gold table to audit"
                    }
                },
                "required": ["table_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_table_stats",
            "description": (
                "Get generic statistics for any table in Supabase: row count, column list with data types, "
                "and null counts per column. Works across bronze, silver, and gold schemas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Table name without schema prefix, e.g. silver_transactions"
                    },
                    "schema_name": {
                        "type": "string",
                        "description": "Schema name, e.g. public_gold, public_silver, public_bronze",
                        "default": "public_gold"
                    }
                },
                "required": ["table_name"]
            }
        }
    }
]
