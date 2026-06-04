"""
Airtable wrapper used by the rest of the bot.

Why a wrapper instead of using pyairtable directly?
    * One place to drop in retries and rate-limit handling
    * Field names come from schema.py (no magic strings)
    * Async-friendly via asyncio.to_thread (pyairtable is sync)
    * Silently no-ops when API key isn't configured (dev mode)

Public API:
    AirtableClient()                # use config from settings
    .upsert_member(...)
    .update_member_status(...)
    .record_payment(...)
    .add_expense(...)
    .record_checklist_event(...)
    .revenue_summary(since, until)
    .expense_summary(since, until)
    .validate_schema()              # used by /airtable_check
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

try:
    from pyairtable import Api as _AirtableApi
    from pyairtable.formulas import match
    _HAVE_PYAIRTABLE = True
except ImportError:
    _HAVE_PYAIRTABLE = False

from airtable.schema import (
    ALL_TABLES,
    ChecklistField,
    ExpenseCategory,
    ExpensesField,
    MembersField,
    MemberStatus,
    PaymentsField,
    PaymentStatus,
)
from config import settings


class AirtableNotConfigured(Exception):
    """Raised internally when key/base ID is missing. Handled by caller."""


class AirtableClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_id: Optional[str] = None,
    ):
        self.api_key = api_key or settings.airtable_api_key
        self.base_id = base_id or settings.airtable_base_id
        self._api = None
        self._base = None

        if not _HAVE_PYAIRTABLE:
            logger.warning("pyairtable not installed — Airtable sync disabled")
            return
        if not self.api_key or not self.base_id:
            logger.warning(
                "AIRTABLE_API_KEY or AIRTABLE_BASE_ID missing — Airtable sync disabled"
            )
            return

        self._api = _AirtableApi(self.api_key)
        self._base = self._api.base(self.base_id)
        logger.info(f"Airtable client ready for base {self.base_id}")

    @property
    def enabled(self) -> bool:
        return self._base is not None

    # ---------- internal helpers ----------

    def _table(self, table_name: str):
        if not self.enabled:
            raise AirtableNotConfigured()
        return self._base.table(table_name)

    async def _run(
        self,
        fn,
        *args,
        max_attempts: int = 4,
        base_delay: float = 1.0,
        **kwargs,
    ):
        """
        Run a blocking pyairtable call in a worker thread with exponential
        backoff on transient failures. Airtable returns 429 on rate-limit
        and occasional 5xx — both are worth retrying.
        """
        last_err: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return await asyncio.to_thread(fn, *args, **kwargs)
            except Exception as e:
                msg = str(e).lower()
                transient = (
                    "429" in msg
                    or "rate limit" in msg
                    or "500" in msg
                    or "502" in msg
                    or "503" in msg
                    or "504" in msg
                    or "timeout" in msg
                )
                last_err = e
                if attempt >= max_attempts or not transient:
                    logger.warning(f"Airtable call failed (final): {e}")
                    return None
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                logger.info(
                    f"Airtable transient error (attempt {attempt}/{max_attempts}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                await asyncio.sleep(delay)
        logger.warning(f"Airtable call exhausted retries: {last_err}")
        return None

    # ---------- Members ----------

    async def upsert_member(
        self,
        *,
        telegram_user_id: int,
        telegram_username: str | None = None,
        name: str | None = None,
        whop_user_id: str | None = None,
        whop_membership_id: str | None = None,
        plan: str | None = None,
        status: MemberStatus | str | None = None,
        join_date: str | None = None,
        email: str | None = None,
    ) -> Optional[dict]:
        """Create-or-update a Members row by Telegram User ID."""
        if not self.enabled:
            return None

        fields: dict[str, Any] = {
            MembersField.TELEGRAM_USER_ID: str(telegram_user_id),
        }
        if telegram_username:
            fields[MembersField.TELEGRAM_USERNAME] = telegram_username
        if name:
            fields[MembersField.NAME] = name
        if whop_user_id:
            fields[MembersField.WHOP_USER_ID] = whop_user_id
        if whop_membership_id:
            fields[MembersField.WHOP_MEMBERSHIP_ID] = whop_membership_id
        if plan:
            fields[MembersField.PLAN] = plan
        if status is not None:
            fields[MembersField.STATUS] = (
                status.value if isinstance(status, MemberStatus) else str(status)
            )
        if join_date:
            fields[MembersField.JOIN_DATE] = join_date
        if email:
            fields[MembersField.EMAIL] = email
        fields[MembersField.LAST_ACTIVITY] = datetime.now(timezone.utc).isoformat()

        table = self._table(settings.airtable_members_table)
        match_formula = match({MembersField.TELEGRAM_USER_ID: str(telegram_user_id)})

        existing = await self._run(table.first, formula=match_formula)
        if existing:
            return await self._run(table.update, existing["id"], fields)
        return await self._run(table.create, fields)

    async def update_member_status(
        self, telegram_user_id: int, status: MemberStatus | str
    ) -> Optional[dict]:
        if not self.enabled:
            return None
        return await self.upsert_member(
            telegram_user_id=telegram_user_id, status=status
        )

    async def append_member_note(
        self,
        telegram_user_id: int,
        note: str,
        *,
        telegram_username: str | None = None,
        name: str | None = None,
        status: MemberStatus | str | None = None,
    ) -> Optional[dict]:
        """Append a line to the member Notes field (creates row if missing)."""
        if not self.enabled:
            return None
        await self.upsert_member(
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            name=name,
            status=status,
        )
        table = self._table(settings.airtable_members_table)
        match_formula = match({MembersField.TELEGRAM_USER_ID: str(telegram_user_id)})
        existing = await self._run(table.first, formula=match_formula)
        if not existing:
            return None
        prev = (existing.get("fields") or {}).get(MembersField.NOTES) or ""
        merged = f"{prev}\n{note}".strip() if prev else note
        fields = {
            MembersField.NOTES: merged,
            MembersField.LAST_ACTIVITY: datetime.now(timezone.utc).isoformat(),
        }
        return await self._run(table.update, existing["id"], fields)

    async def record_terms_accepted(
        self,
        telegram_user_id: int,
        *,
        telegram_username: str | None = None,
        name: str | None = None,
        accepted_at_iso: str,
    ) -> Optional[dict]:
        """Log T&C acceptance on the member row (Notes + ensure row exists)."""
        return await self.append_member_note(
            telegram_user_id,
            f"T&C accepted at {accepted_at_iso}",
            telegram_username=telegram_username,
            name=name,
            status=MemberStatus.PENDING,
        )

    async def mark_onboarding_complete(
        self, telegram_user_id: int
    ) -> Optional[dict]:
        if not self.enabled:
            return None
        table = self._table(settings.airtable_members_table)
        match_formula = match({MembersField.TELEGRAM_USER_ID: str(telegram_user_id)})
        existing = await self._run(table.first, formula=match_formula)
        if not existing:
            return None
        fields = {
            MembersField.ONBOARDING_COMPLETED: True,
            MembersField.ONBOARDING_COMPLETED_AT: datetime.now(timezone.utc).isoformat(),
        }
        return await self._run(table.update, existing["id"], fields)

    async def find_member_record_id(self, telegram_user_id: int) -> Optional[str]:
        if not self.enabled:
            return None
        table = self._table(settings.airtable_members_table)
        match_formula = match({MembersField.TELEGRAM_USER_ID: str(telegram_user_id)})
        rec = await self._run(table.first, formula=match_formula)
        return rec["id"] if rec else None

    # ---------- Payments ----------

    async def record_payment(
        self,
        *,
        payment_id: str,
        telegram_user_id: int | None,
        amount: float,
        currency: str,
        plan: str | None = None,
        status: PaymentStatus | str = PaymentStatus.SUCCEEDED,
        date_iso: str | None = None,
        whop_user_id: str | None = None,
        notes: str | None = None,
    ) -> Optional[dict]:
        if not self.enabled:
            return None

        fields: dict[str, Any] = {
            PaymentsField.PAYMENT_ID: payment_id,
            PaymentsField.AMOUNT: float(amount),
            PaymentsField.CURRENCY: currency.upper(),
            PaymentsField.DATE: date_iso or datetime.now(timezone.utc).isoformat(),
            PaymentsField.STATUS: (
                status.value if isinstance(status, PaymentStatus) else str(status)
            ),
        }
        if plan:
            fields[PaymentsField.PLAN] = plan
        if whop_user_id:
            fields[PaymentsField.WHOP_USER_ID] = whop_user_id
        if notes:
            fields[PaymentsField.NOTES] = notes

        if telegram_user_id is not None:
            member_rec_id = await self.find_member_record_id(telegram_user_id)
            if member_rec_id:
                fields[PaymentsField.MEMBER] = [member_rec_id]

        table = self._table(settings.airtable_payments_table)
        existing = await self._run(
            table.first, formula=match({PaymentsField.PAYMENT_ID: payment_id})
        )
        if existing:
            return await self._run(table.update, existing["id"], fields)
        return await self._run(table.create, fields)

    # ---------- Expenses ----------

    async def add_expense(
        self,
        *,
        amount: float,
        currency: str,
        category: ExpenseCategory | str,
        description: str,
        added_by: str | None = None,
        date_iso: str | None = None,
        notes: str | None = None,
    ) -> Optional[dict]:
        if not self.enabled:
            return None

        fields: dict[str, Any] = {
            ExpensesField.AMOUNT: float(amount),
            ExpensesField.CURRENCY: currency.upper(),
            ExpensesField.CATEGORY: (
                category.value if isinstance(category, ExpenseCategory) else str(category)
            ),
            ExpensesField.DESCRIPTION: description,
            ExpensesField.DATE: date_iso or datetime.now(timezone.utc).isoformat(),
        }
        if added_by:
            fields[ExpensesField.ADDED_BY] = added_by
        if notes:
            fields[ExpensesField.NOTES] = notes

        table = self._table(settings.airtable_expenses_table)
        return await self._run(table.create, fields)

    # ---------- Checklist activity ----------

    async def record_checklist_event(
        self,
        *,
        telegram_user_id: int,
        task_id: str,
        task_title: str,
        completed: bool,
    ) -> Optional[dict]:
        if not self.enabled:
            return None

        fields: dict[str, Any] = {
            ChecklistField.TELEGRAM_USER_ID: str(telegram_user_id),
            ChecklistField.TASK_ID: task_id,
            ChecklistField.TASK_TITLE: task_title,
            ChecklistField.COMPLETED: completed,
            ChecklistField.COMPLETED_AT: datetime.now(timezone.utc).isoformat(),
        }
        member_rec_id = await self.find_member_record_id(telegram_user_id)
        if member_rec_id:
            fields[ChecklistField.MEMBER] = [member_rec_id]

        table = self._table(settings.airtable_checklist_table)
        return await self._run(table.create, fields)

    # ---------- Reporting ----------

    async def revenue_summary(
        self, since: datetime | None = None, until: datetime | None = None
    ) -> dict:
        """Return totals by currency for succeeded payments in the window."""
        if not self.enabled:
            return {"by_currency": {}, "count": 0}

        table = self._table(settings.airtable_payments_table)
        records = await self._run(table.all) or []

        totals: dict[str, float] = {}
        count = 0
        for r in records:
            f = r.get("fields", {})
            if f.get(PaymentsField.STATUS) != PaymentStatus.SUCCEEDED.value:
                continue
            date_str = f.get(PaymentsField.DATE)
            if date_str:
                try:
                    when = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if since and when < since:
                    continue
                if until and when > until:
                    continue
            currency = (f.get(PaymentsField.CURRENCY) or "USD").upper()
            amount = float(f.get(PaymentsField.AMOUNT) or 0)
            totals[currency] = totals.get(currency, 0.0) + amount
            count += 1

        return {"by_currency": totals, "count": count}

    async def expense_summary(
        self, since: datetime | None = None, until: datetime | None = None
    ) -> dict:
        if not self.enabled:
            return {"by_currency": {}, "by_category": {}, "count": 0}

        table = self._table(settings.airtable_expenses_table)
        records = await self._run(table.all) or []

        by_currency: dict[str, float] = {}
        by_category: dict[str, float] = {}
        count = 0
        for r in records:
            f = r.get("fields", {})
            date_str = f.get(ExpensesField.DATE)
            if date_str:
                try:
                    when = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if since and when < since:
                    continue
                if until and when > until:
                    continue
            currency = (f.get(ExpensesField.CURRENCY) or "USD").upper()
            amount = float(f.get(ExpensesField.AMOUNT) or 0)
            category = f.get(ExpensesField.CATEGORY) or "Other"
            by_currency[currency] = by_currency.get(currency, 0.0) + amount
            by_category[category] = by_category.get(category, 0.0) + amount
            count += 1

        return {
            "by_currency": by_currency,
            "by_category": by_category,
            "count": count,
        }

    # ---------- Schema validation ----------

    async def validate_schema(self) -> dict:
        """Probe each configured table and confirm required fields exist."""
        if not self.enabled:
            return {"ok": False, "reason": "Airtable client not configured"}

        results: dict[str, dict] = {}
        table_map = {
            "members": settings.airtable_members_table,
            "payments": settings.airtable_payments_table,
            "expenses": settings.airtable_expenses_table,
            "checklist": settings.airtable_checklist_table,
        }

        for short, table_name in table_map.items():
            required = ALL_TABLES[short]
            try:
                table = self._base.table(table_name)
                sample = await self._run(table.first)
                if sample is None:
                    results[short] = {
                        "ok": True,
                        "table": table_name,
                        "note": "empty (could not verify fields)",
                        "missing": [],
                    }
                    continue
                present = set((sample.get("fields") or {}).keys())
                missing = [f for f in required if f not in present]
                results[short] = {
                    "ok": not missing,
                    "table": table_name,
                    "missing": missing,
                }
            except Exception as e:
                results[short] = {
                    "ok": False,
                    "table": table_name,
                    "error": str(e)[:200],
                }

        results["all_ok"] = all(v.get("ok") for k, v in results.items() if k != "all_ok")
        return results
