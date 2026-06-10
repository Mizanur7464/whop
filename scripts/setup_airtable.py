#!/usr/bin/env python3
"""
Create / update Airtable CRM tables from .env.

Usage:
    python scripts/setup_airtable.py

Creates missing tables and adds any missing columns on existing tables.
Requires AIRTABLE_API_KEY with ``schema.bases:write`` on the base.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from airtable.schema_migrate import migrate_airtable_schema


def main() -> int:
    report = migrate_airtable_schema(create_missing_tables=True)
    if report.get("reason"):
        print(f"Error: {report['reason']}")
        return 1

    print(f"Base schema sync — ok={report.get('ok')}")
    if report.get("deprecated_table"):
        print(f"  {report['deprecated_table']}")
    for table_name, info in report.get("tables", {}).items():
        if info.get("created"):
            print(f"  created table {table_name}")
        added = info.get("added") or []
        fixed = info.get("fixed") or []
        if added:
            print(f"  {table_name}: added {', '.join(added)}")
        if fixed:
            print(f"  {table_name}: fixed {', '.join(fixed)}")
        errors = info.get("errors") or []
        for err in errors:
            print(f"  {table_name}: ERROR {err}")
        error = info.get("error")
        if error:
            print(f"  {table_name}: ERROR {error}")

    print("\nDone. Run /airtable_check in Telegram to verify.")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
