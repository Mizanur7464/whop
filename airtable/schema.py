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
    PHONE = "Phone"
    PLATFORM = "Platform"
    PLATFORM_USER_ID = "Platform User ID"
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


class TradingPlatform(str, Enum):
    VANTAGE = "Vantage"
    PREMIER = "Premier"


TRADING_PLATFORMS = frozenset(p.value for p in TradingPlatform)


# ---------- Unified Finance table (payments + expenses) ----------

class FinanceField:
    ENTRY_ID = "Entry ID"
    TYPE = "Type"
    MEMBER = "Member"
    AMOUNT = "Amount"
    FEES = "Fees"
    NET_AMOUNT = "Net Amount"
    CURRENCY = "Currency"
    DATE = "Date"
    WHOP_USER_ID = "Whop User ID"
    PLAN = "Plan"
    STATUS = "Status"
    CATEGORY = "Category"
    DESCRIPTION = "Description"
    ADDED_BY = "Added By"
    NOTES = "Notes"


class FinanceType(str, Enum):
    PAYMENT = "Payment"
    EXPENSE = "Expense"


# ---------- Legacy field aliases (Finance table) ----------

class PaymentsField:
    PAYMENT_ID = FinanceField.ENTRY_ID
    MEMBER = FinanceField.MEMBER
    WHOP_USER_ID = FinanceField.WHOP_USER_ID
    AMOUNT = FinanceField.AMOUNT
    FEES = FinanceField.FEES
    NET_AMOUNT = FinanceField.NET_AMOUNT
    CURRENCY = FinanceField.CURRENCY
    PLAN = FinanceField.PLAN
    DATE = FinanceField.DATE
    STATUS = FinanceField.STATUS
    NOTES = FinanceField.NOTES


# ---------- Payments table (deprecated — use Finance) ----------

class PaymentStatus(str, Enum):
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    REFUNDED = "Refunded"


# ---------- Expenses table ----------

class ExpensesField:
    DATE = FinanceField.DATE
    CATEGORY = FinanceField.CATEGORY
    AMOUNT = FinanceField.AMOUNT
    FEES = FinanceField.FEES
    NET_AMOUNT = FinanceField.NET_AMOUNT
    CURRENCY = FinanceField.CURRENCY
    DESCRIPTION = FinanceField.DESCRIPTION
    ADDED_BY = FinanceField.ADDED_BY
    NOTES = FinanceField.NOTES


class Currency(str, Enum):
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"


SUPPORTED_CURRENCIES = frozenset(c.value for c in Currency)


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
        MembersField.EMAIL,
        MembersField.PHONE,
        MembersField.PLATFORM,
        MembersField.PLATFORM_USER_ID,
        MembersField.WHOP_USER_ID,
        MembersField.PLAN,
        MembersField.STATUS,
        MembersField.JOIN_DATE,
    ],
    "finance": [
        FinanceField.ENTRY_ID,
        FinanceField.TYPE,
        FinanceField.AMOUNT,
        FinanceField.FEES,
        FinanceField.NET_AMOUNT,
        FinanceField.CURRENCY,
        FinanceField.DATE,
    ],
    "checklist": [
        ChecklistField.TELEGRAM_USER_ID,
        ChecklistField.TASK_ID,
        ChecklistField.COMPLETED,
    ],
}
