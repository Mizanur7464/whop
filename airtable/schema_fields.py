"""
Airtable table field definitions for create / migrate scripts.

Field names must match airtable/schema.py constants.
"""

from __future__ import annotations

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


def finance_entry_id_field_name() -> str:
    """Legacy Payments table uses ``Payment ID`` instead of ``Entry ID``."""
    if (
        settings.airtable_finance_table.strip().lower()
        == settings.airtable_payments_table.strip().lower()
    ):
        return "Payment ID"
    return "Entry ID"


def members_fields() -> list[dict]:
    return [
        {"name": "Telegram User ID", "type": "singleLineText"},
        {"name": "Telegram Username", "type": "singleLineText"},
        {"name": "Name", "type": "singleLineText"},
        {"name": "Email", "type": "email"},
        {"name": "Phone", "type": "singleLineText"},
        _select("Platform", ["Vantage", "Premier"]),
        {"name": "Platform User ID", "type": "singleLineText"},
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


def finance_fields(members_table_id: str) -> list[dict]:
    return [
        {"name": finance_entry_id_field_name(), "type": "singleLineText"},
        _select("Type", ["Payment", "Expense"]),
        _link("Member", members_table_id),
        _number("Amount"),
        _number("Fees"),
        _number("Net Amount"),
        _select("Currency", ["EUR", "USD", "GBP"]),
        _date("Date"),
        {"name": "Whop User ID", "type": "singleLineText"},
        {"name": "Plan", "type": "singleLineText"},
        _select("Status", ["Succeeded", "Failed", "Refunded"]),
        _select(
            "Category",
            ["Ads", "Tools", "Salary", "Software", "Hosting", "Other"],
        ),
        {"name": "Description", "type": "multilineText"},
        {"name": "Added By", "type": "singleLineText"},
        {"name": "Notes", "type": "multilineText"},
    ]


def checklist_fields(members_table_id: str) -> list[dict]:
    return [
        {"name": "Telegram User ID", "type": "singleLineText"},
        _link("Member", members_table_id),
        {"name": "Task ID", "type": "singleLineText"},
        {"name": "Task Title", "type": "singleLineText"},
        _checkbox("Completed"),
        _date("Completed At"),
    ]


FIELD_ALIASES: dict[str, frozenset[str]] = {
    "Entry ID": frozenset({"Payment ID"}),
    "Payment ID": frozenset({"Entry ID"}),
}


def field_is_present(name: str, present: set[str]) -> bool:
    if name in present:
        return True
    return bool(FIELD_ALIASES.get(name, frozenset()) & present)
