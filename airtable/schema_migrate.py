"""
Add missing Airtable columns (and tables) to match the bot schema.

Used by ``scripts/setup_airtable.py`` and the ``/airtable_setup`` admin command.
Requires an API token with ``schema.bases:write`` on the base.
"""

from __future__ import annotations

import logging
from typing import Any

from pyairtable import Api

from airtable.schema import FinanceField
from airtable.schema_fields import (
    checklist_fields,
    field_is_present,
    finance_fields,
    members_fields,
)
from config import settings

logger = logging.getLogger(__name__)

_FINANCE_SELECT_FIXES: dict[str, list[str]] = {
    FinanceField.CURRENCY: ["EUR", "USD", "GBP"],
    FinanceField.TYPE: ["Payment", "Expense"],
}

_DEPRECATED_EXPENSES_NAME = "Expenses (deprecated — use Payments)"


def _table_field_names(base_schema, table_name: str) -> set[str]:
    try:
        table_schema = base_schema.table(table_name)
    except KeyError:
        return set()
    return {field.name for field in table_schema.fields}


def _get_field_schema(base_schema, table_name: str, field_name: str):
    try:
        table_schema = base_schema.table(table_name)
    except KeyError:
        return None
    for field in table_schema.fields:
        if field.name == field_name:
            return field
    return None


def _recreate_select_field(
    api,
    *,
    base_id: str,
    api_table,
    base_schema,
    field_name: str,
    choices: list[str],
) -> str | None:
    """Replace a non-select field with a single-select (buyer CRM requirement)."""
    field = _get_field_schema(base_schema, api_table.name, field_name)
    if field is None or field.type == "singleSelect":
        return None

    try:
        api.delete(f"meta/bases/{base_id}/tables/{api_table.id}/fields/{field.id}")
        api_table.create_field(
            field_name,
            "singleSelect",
            options={"choices": [{"name": c} for c in choices]},
        )
        return f"recreated {field_name} as select"
    except Exception as e:
        logger.warning("Could not recreate select field %s: %s", field_name, e)
        return f"{field_name}: could not convert to select ({e})"


def _deprecate_legacy_expenses_table(api, base_schema) -> str | None:
    """Rename old standalone Expenses table so buyer uses unified Payments only."""
    legacy = settings.airtable_expenses_table.strip()
    finance = settings.airtable_finance_table.strip()
    if not legacy or legacy.lower() == finance.lower():
        return None
    if legacy.startswith("Expenses (deprecated"):
        return None

    try:
        table_schema = base_schema.table(legacy)
    except KeyError:
        return None

    if table_schema.name == _DEPRECATED_EXPENSES_NAME:
        return None

    try:
        table_schema.name = _DEPRECATED_EXPENSES_NAME
        table_schema.save()
        return f"renamed {legacy} → {_DEPRECATED_EXPENSES_NAME}"
    except Exception as e:
        logger.warning("Could not rename legacy Expenses table: %s", e)
        return f"{legacy}: could not rename ({e})"


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


def _fix_finance_field_types(
    api,
    *,
    base_id: str,
    api_table,
    base_schema,
) -> tuple[list[str], list[str]]:
    fixed: list[str] = []
    errors: list[str] = []
    for field_name, choices in _FINANCE_SELECT_FIXES.items():
        result = _recreate_select_field(
            api,
            base_id=base_id,
            api_table=api_table,
            base_schema=base_schema,
            field_name=field_name,
            choices=choices,
        )
        if result is None:
            continue
        if result.startswith("recreated"):
            fixed.append(result)
        else:
            errors.append(result)
    return fixed, errors


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

    deprecated = _deprecate_legacy_expenses_table(api, base_schema)
    if deprecated:
        report["deprecated_table"] = deprecated
        base_schema = base.schema(force=True)

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
                "fixed": [],
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
        fixed: list[str] = []
        if table_name == settings.airtable_finance_table:
            type_fixed, type_errors = _fix_finance_field_types(
                api,
                base_id=settings.airtable_base_id,
                api_table=tbl,
                base_schema=base_schema,
            )
            fixed.extend(type_fixed)
            errors.extend(type_errors)
            if type_fixed:
                base_schema = base.schema(force=True)

        report["tables"][table_name] = {
            "ok": not errors,
            "created": False,
            "added": added,
            "fixed": fixed,
            "errors": errors,
        }
        if errors:
            report["ok"] = False

    return report
