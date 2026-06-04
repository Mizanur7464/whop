#!/usr/bin/env python3
"""
Create the four CRM tables in the Airtable base from .env (if missing).

Usage:
    python scripts/setup_airtable.py

Requires AIRTABLE_API_KEY with access to AIRTABLE_BASE_ID and permission
to create tables (schema.bases:write or full base access on the token).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyairtable import Api

from config import settings


def _select(name: str, choices: list[str]) -> dict:
    return {
        "name": name,
        "type": "singleSelect",
        "options": {"choices": [{"name": c} for c in choices]},
    }


def _date(name: str) -> dict:
    return {
        "name": name,
        "type": "dateTime",
        "options": {
            "dateFormat": {"name": "iso"},
            "timeFormat": {"name": "24hour"},
            "timeZone": "utc",
        },
    }


def _number(name: str, precision: int = 2) -> dict:
    return {
        "name": name,
        "type": "number",
        "options": {"precision": precision},
    }


def _checkbox(name: str) -> dict:
    return {
        "name": name,
        "type": "checkbox",
        "options": {"icon": "check", "color": "greenBright"},
    }


def _link(name: str, linked_table_id: str) -> dict:
    return {
        "name": name,
        "type": "multipleRecordLinks",
        "options": {"linkedTableId": linked_table_id},
    }


def members_fields() -> list[dict]:
    return [
        {"name": "Telegram User ID", "type": "singleLineText"},
        {"name": "Telegram Username", "type": "singleLineText"},
        {"name": "Name", "type": "singleLineText"},
        {"name": "Email", "type": "email"},
        {"name": "Whop User ID", "type": "singleLineText"},
        {"name": "Whop Membership ID", "type": "singleLineText"},
        _select("Plan", ["Basic", "Premium", "VIP", "unknown"]),
        _select("Status", ["Active", "Expired", "Banned", "Pending"]),
        _date("Join Date"),
        _checkbox("Onboarding Completed"),
        _date("Onboarding Completed At"),
        _date("Last Activity"),
        _number("Reminders Sent", precision=0),
        _checkbox("Cancel At Period End"),
        {"name": "Notes", "type": "multilineText"},
    ]


def payments_fields(members_table_id: str) -> list[dict]:
    return [
        {"name": "Payment ID", "type": "singleLineText"},
        _link("Member", members_table_id),
        {"name": "Whop User ID", "type": "singleLineText"},
        _number("Amount"),
        {"name": "Currency", "type": "singleLineText"},
        {"name": "Plan", "type": "singleLineText"},
        _date("Date"),
        _select("Status", ["Succeeded", "Failed", "Refunded"]),
        {"name": "Notes", "type": "multilineText"},
    ]


def expenses_fields() -> list[dict]:
    return [
        _date("Date"),
        _select("Category", ["Ads", "Tools", "Salary", "Software", "Hosting", "Other"]),
        _number("Amount"),
        {"name": "Currency", "type": "singleLineText"},
        {"name": "Description", "type": "multilineText"},
        {"name": "Added By", "type": "singleLineText"},
        {"name": "Notes", "type": "multilineText"},
    ]


def checklist_fields(members_table_id: str) -> list[dict]:
    # Primary field must be text; add Member link after table exists (see main()).
    return [
        {"name": "Telegram User ID", "type": "singleLineText"},
        {"name": "Task ID", "type": "singleLineText"},
        {"name": "Task Title", "type": "singleLineText"},
        _checkbox("Completed"),
        _date("Completed At"),
        _link("Member", members_table_id),
    ]


def main() -> int:
    if not settings.airtable_api_key or not settings.airtable_base_id:
        print("Set AIRTABLE_API_KEY and AIRTABLE_BASE_ID in .env first.")
        return 1

    api = Api(settings.airtable_api_key)
    base = api.base(settings.airtable_base_id)
    existing = {t.name for t in base.schema().tables}
    print(f"Base {settings.airtable_base_id} — existing tables: {sorted(existing)}")

    plan = [
        (settings.airtable_members_table, None),
        (settings.airtable_payments_table, "members"),
        (settings.airtable_expenses_table, None),
        (settings.airtable_checklist_table, "members"),
    ]

    created_ids: dict[str, str] = {}

    for table_name, needs_members in plan:
        if table_name in existing:
            tbl = base.table(table_name)
            created_ids[table_name] = tbl.id
            print(f"  skip {table_name} (already exists)")
            continue

        if needs_members == "members":
            members_name = settings.airtable_members_table
            if members_name not in created_ids:
                print(f"  error: create {members_name} before {table_name}")
                return 1
            fields_fn = {
                settings.airtable_payments_table: lambda: payments_fields(
                    created_ids[members_name]
                ),
                settings.airtable_checklist_table: lambda: checklist_fields(
                    created_ids[members_name]
                ),
            }[table_name]
            fields = fields_fn()
        elif table_name == settings.airtable_members_table:
            fields = members_fields()
        elif table_name == settings.airtable_expenses_table:
            fields = expenses_fields()
        else:
            print(f"  unknown table plan for {table_name}")
            return 1

        print(f"  creating {table_name}...")
        tbl = base.create_table(table_name, fields=fields)
        created_ids[table_name] = tbl.id
        print(f"  created {table_name} ({tbl.id})")

    print("\nDone. Run /airtable_check in Telegram to verify.")
    if "Table 1" in existing or "MembersTest" in existing:
        print("Optional: delete unused tables 'Table 1' / 'MembersTest' in Airtable UI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
