import json
import os

GOLD = os.environ.get("GOLD_SCHEMA", "public_gold")

_TABLE_MAP = {
    "monthly": "gold_fct_monthly_premiums",
    "premium": "gold_fct_monthly_premiums",
    "reconciliation": "gold_fct_accounting_reconciliation",
    "accounting": "gold_fct_accounting_reconciliation",
    "customer": "gold_fct_customer_activity_daily",
    "daily": "gold_fct_customer_activity_daily",
    "activity": "gold_fct_customer_activity_daily",
}


def _resolve_table(table: str | None) -> str:
    if not table:
        return "gold_fct_monthly_premiums"
    for key, full in _TABLE_MAP.items():
        if key in table:
            return full
    return table


def _parse_results(raw: dict) -> tuple[list, list]:
    passed, failed = [], []

    for check, result in raw.items():
        if "error" in result:
            failed.append(f"❌ **{check}**: {result['error']}")
            continue

        rows = result.get("rows", [{}])
        row = rows[0] if rows else {}

        if check == "row_count":
            passed.append(f"✅ **row_count**: {row.get('total_rows', 0)} rows")

        elif "null_check" in check:
            bad = {k: v for k, v in row.items() if v and int(v) > 0}
            if bad:
                failed.append(f"❌ **null_check**: nulls found — {bad}")
            else:
                passed.append("✅ **null_check**: no nulls in required columns")

        elif "uniqueness" in check:
            dupes = int(row.get("duplicate_grain_rows", 0))
            if dupes:
                failed.append(f"❌ **uniqueness**: {dupes} duplicate grain rows")
            else:
                passed.append("✅ **uniqueness**: grain (party, month) is unique")

        elif "invalid" in check:
            if any(row.values()):
                failed.append(f"❌ **{check}**: unexpected values — {rows[:3]}")
            else:
                passed.append(f"✅ **{check}**: all values within accepted set")

        elif "sanity" in check:
            bad = int(row.get("rows_where_net_ne_written_minus_refunded", 0))
            if bad:
                failed.append(f"❌ **sanity**: {bad} rows fail net_premium = written − refunded")
            else:
                passed.append("✅ **sanity**: net_premium math is consistent")

        elif check in ("status_distribution", "summary_by_party", "customer_summary",
                       "top_discrepancies", "date_range", "product_group_breakdown"):
            passed.append(f"✅ **{check}**: computed ({len(rows)} rows)")

    return passed, failed


def run(intent: dict, db) -> dict:
    from main import _check_data_quality  # imported here to avoid circular dep at module load

    table = _resolve_table(intent.get("table"))
    raw = json.loads(_check_data_quality(table))
    passed, failed = _parse_results(raw)

    return {
        "success": len(failed) == 0,
        "table": f"{GOLD}.{table}",
        "checks_passed": len(passed),
        "checks_failed": len(failed),
        "passed": passed,
        "failed": failed,
    }
