"""
Add missing Airtable columns (and tables) to match the bot schema.

Used by ``scripts/setup_airtable.py`` and the ``/airtable_setup`` admin command.
Requires an API token with ``schema.bases:write`` on the base.
"""

from __future__ import annotations

import logging
from typing import Any

from pyairtable import Api

from airtable.schema_fields import (
    checklist_fields,
    field_is_present,
    finance_fields,
    members_fields,
)
from config import settings

logger = logging.getLogger(__name__)


def _table_field_names(base_schema, table_name: str) -> set[str]:
    try:
        table_schema = base_schema.table(table_name)
    except KeyError:
        return set()
    return {field.name for field in table_schema.fields}


def _add_missing_fields(
    api_table,
    *,
    desired: list[dict[str, Any]],
    present: set[str],
) -> tuple[list[str], list[str]]:
    added: list[str] = []
    errors: list[str] = []
    for spec in desired:
        name = spec["name"]
        if field_is_present(name, present):
            continue
        try:
            api_table.create_field(
                name,
                spec["type"],
                options=spec.get("options"),
            )
            added.append(name)
            present.add(name)
            logger.info("Airtable: added field %s on %s", name, api_table.name)
        except Exception as e:
            msg = f"{name}: {e}"
            errors.append(msg)
            logger.warning("Airtable: could not add field %s — %s", name, e)
    return added, errors


def migrate_airtable_schema(*, create_missing_tables: bool = True) -> dict[str, Any]:
    """
    Ensure Members, Finance/Payments, and Checklist tables exist with all fields.

    Returns a report dict suitable for admin messages and CLI output.
    """
    if not settings.airtable_api_key or not settings.airtable_base_id:
        return {"ok": False, "reason": "AIRTABLE_API_KEY or AIRTABLE_BASE_ID not set"}

    api = Api(settings.airtable_api_key)
    base = api.base(settings.airtable_base_id)
    base_schema = base.schema()
    existing_tables = {t.name for t in base_schema.tables}

    report: dict[str, Any] = {"ok": True, "tables": {}, "reason": None}
    table_ids: dict[str, str] = {}

    plan = [
        (settings.airtable_members_table, None),
        (settings.airtable_finance_table, "members"),
        (settings.airtable_checklist_table, "members"),
    ]

    for table_name, needs_members in plan:
        if table_name not in existing_tables:
            if not create_missing_tables:
                report["tables"][table_name] = {
                    "ok": False,
                    "error": "table missing (run with create_missing_tables=True)",
                }
                report["ok"] = False
                continue

            members_id = table_ids.get(settings.airtable_members_table)
            if needs_members == "members" and not members_id:
                report["tables"][table_name] = {
                    "ok": False,
                    "error": f"{settings.airtable_members_table} must exist first",
                }
                report["ok"] = False
                continue

            if table_name == settings.airtable_members_table:
                fields = members_fields()
            elif table_name == settings.airtable_finance_table:
                fields = finance_fields(members_id or "")
            else:
                fields = checklist_fields(members_id or "")

            tbl = base.create_table(table_name, fields=fields)
            table_ids[table_name] = tbl.id
            report["tables"][table_name] = {
                "ok": True,
                "created": True,
                "added": [f["name"] for f in fields],
                "errors": [],
            }
            base_schema = base.schema(force=True)
            existing_tables.add(table_name)
            continue

        tbl = base.table(table_name)
        table_ids[table_name] = tbl.id
        present = _table_field_names(base_schema, table_name)

        if table_name == settings.airtable_members_table:
            desired = members_fields()
        elif table_name == settings.airtable_finance_table:
            members_id = table_ids.get(settings.airtable_members_table)
            if not members_id:
                members_id = base.table(settings.airtable_members_table).id
            desired = finance_fields(members_id)
        else:
            members_id = table_ids.get(settings.airtable_members_table)
            if not members_id:
                members_id = base.table(settings.airtable_members_table).id
            desired = checklist_fields(members_id)

        added, errors = _add_missing_fields(tbl, desired=desired, present=present)
        report["tables"][table_name] = {
            "ok": not errors,
            "created": False,
            "added": added,
            "errors": errors,
        }
        if errors:
            report["ok"] = False

    return report
