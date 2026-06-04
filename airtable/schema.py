"""
Canonical Airtable schema for the project.

The buyer creates the base manually in Airtable (we document it in
docs/AIRTABLE_SETUP.md). This module is the single source of truth for
field names so the rest of the code can never typo a field.

If the buyer renames a field in Airtable, update the constants here
and nothing else needs to change.
"""

from __future__ import annotations

from enum import Enum


# ---------- Members table ----------

class MembersField:
    TELEGRAM_USER_ID = "Telegram User ID"
    TELEGRAM_USERNAME = "Telegram Username"
    NAME = "Name"
    EMAIL = "Email"
    WHOP_USER_ID = "Whop User ID"
    WHOP_MEMBERSHIP_ID = "Whop Membership ID"
    PLAN = "Plan"
    STATUS = "Status"
    JOIN_DATE = "Join Date"
    ONBOARDING_COMPLETED = "Onboarding Completed"
    ONBOARDING_COMPLETED_AT = "Onboarding Completed At"
    LAST_ACTIVITY = "Last Activity"
    REMINDERS_SENT = "Reminders Sent"
    CANCEL_AT_PERIOD_END = "Cancel At Period End"
    NOTES = "Notes"


class MemberStatus(str, Enum):
    ACTIVE = "Active"
    EXPIRED = "Expired"
    BANNED = "Banned"
    PENDING = "Pending"


# ---------- Payments table ----------

class PaymentsField:
    PAYMENT_ID = "Payment ID"
    MEMBER = "Member"               # link to Members
    WHOP_USER_ID = "Whop User ID"   # denormalized for filtering
    AMOUNT = "Amount"
    CURRENCY = "Currency"
    PLAN = "Plan"
    DATE = "Date"
    STATUS = "Status"
    NOTES = "Notes"


class PaymentStatus(str, Enum):
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    REFUNDED = "Refunded"


# ---------- Expenses table ----------

class ExpensesField:
    DATE = "Date"
    CATEGORY = "Category"
    AMOUNT = "Amount"
    CURRENCY = "Currency"
    DESCRIPTION = "Description"
    ADDED_BY = "Added By"           # Telegram username
    NOTES = "Notes"


class ExpenseCategory(str, Enum):
    ADS = "Ads"
    TOOLS = "Tools"
    SALARY = "Salary"
    SOFTWARE = "Software"
    HOSTING = "Hosting"
    OTHER = "Other"


# ---------- Checklist Activity table ----------

class ChecklistField:
    MEMBER = "Member"               # link to Members
    TELEGRAM_USER_ID = "Telegram User ID"
    TASK_ID = "Task ID"
    TASK_TITLE = "Task Title"
    COMPLETED = "Completed"
    COMPLETED_AT = "Completed At"


# ---------- Lookup helpers ----------

ALL_TABLES = {
    "members": [
        MembersField.TELEGRAM_USER_ID,
        MembersField.TELEGRAM_USERNAME,
        MembersField.NAME,
        MembersField.WHOP_USER_ID,
        MembersField.PLAN,
        MembersField.STATUS,
        MembersField.JOIN_DATE,
    ],
    "payments": [
        PaymentsField.PAYMENT_ID,
        PaymentsField.AMOUNT,
        PaymentsField.CURRENCY,
        PaymentsField.DATE,
        PaymentsField.STATUS,
    ],
    "expenses": [
        ExpensesField.DATE,
        ExpensesField.CATEGORY,
        ExpensesField.AMOUNT,
        ExpensesField.CURRENCY,
        ExpensesField.DESCRIPTION,
    ],
    "checklist": [
        ChecklistField.TELEGRAM_USER_ID,
        ChecklistField.TASK_ID,
        ChecklistField.COMPLETED,
    ],
}
