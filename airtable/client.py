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
    Currency,
    ExpenseCategory,
    ExpensesField,
    FinanceField,
    FinanceType,
    MembersField,
    MemberStatus,
    PaymentsField,
    PaymentStatus,
    SUPPORTED_CURRENCIES,
    TRADING_PLATFORMS,
)
from config import settings


def normalize_currency(raw: str | None) -> str:
    code = (raw or "USD").strip().upper()
    if code in SUPPORTED_CURRENCIES:
        return code
    logger.warning(
        f"Airtable currency {code!r} not in {sorted(SUPPORTED_CURRENCIES)} — storing as USD"
    )
    return Currency.USD.value


def normalize_trading_platform(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if value.lower() == "vantage":
        return "Vantage"
    if value.lower() == "premier":
        return "Premier"
    if value in TRADING_PLATFORMS:
        return value
    return None


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

    PLACEHOLDER_TG_PREFIX = "whop:"

    @classmethod
    def _is_placeholder_telegram_id(cls, telegram_user_id: str | None) -> bool:
        return bool(
            telegram_user_id
            and str(telegram_user_id).startswith(cls.PLACEHOLDER_TG_PREFIX)
        )

    @classmethod
    def _placeholder_telegram_id(cls, whop_user_id: str) -> str:
        return f"{cls.PLACEHOLDER_TG_PREFIX}{whop_user_id}"

    async def find_member_by_whop_user_id(self, whop_user_id: str) -> Optional[dict]:
        if not self.enabled:
            return None
        table = self._table(settings.airtable_members_table)
        match_formula = match({MembersField.WHOP_USER_ID: whop_user_id})
        return await self._run(table.first, formula=match_formula)

    async def upsert_whop_member(
        self,
        *,
        whop_user_id: str,
        whop_membership_id: str | None = None,
        plan: str | None = None,
        status: MemberStatus | str | None = None,
        join_date: str | None = None,
        email: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        telegram_user_id: int | None = None,
        telegram_username: str | None = None,
        telegram_claimed: bool | None = None,
        platform: str | None = None,
        platform_user_id: str | None = None,
    ) -> Optional[dict]:
        """Create-or-update a Members row keyed by Whop User ID."""
        if not self.enabled:
            return None

        existing = await self.find_member_by_whop_user_id(whop_user_id)
        table = self._table(settings.airtable_members_table)
        if not existing and telegram_user_id:
            existing = await self._run(
                table.first,
                formula=match({MembersField.TELEGRAM_USER_ID: str(telegram_user_id)}),
            )

        fields: dict[str, Any] = {
            MembersField.WHOP_USER_ID: whop_user_id,
            MembersField.LAST_ACTIVITY: datetime.now(timezone.utc).isoformat(),
        }
        if whop_membership_id:
            fields[MembersField.WHOP_MEMBERSHIP_ID] = whop_membership_id
        plan_value = self._plan_field(plan)
        if plan_value:
            fields[MembersField.PLAN] = plan_value
        if status is not None:
            fields[MembersField.STATUS] = (
                status.value if isinstance(status, MemberStatus) else str(status)
            )
        elif not existing:
            fields[MembersField.STATUS] = MemberStatus.PENDING.value
        if join_date:
            fields[MembersField.JOIN_DATE] = join_date
        if email:
            fields[MembersField.EMAIL] = email
        if name:
            fields[MembersField.NAME] = name
        if phone:
            fields[MembersField.PHONE] = phone
        platform_value = normalize_trading_platform(platform)
        if platform_value:
            fields[MembersField.PLATFORM] = platform_value
        if platform_user_id:
            fields[MembersField.PLATFORM_USER_ID] = platform_user_id.strip()
        if telegram_username:
            fields[MembersField.TELEGRAM_USERNAME] = telegram_username
        if telegram_claimed is not None:
            fields[MembersField.TELEGRAM_CLAIMED] = telegram_claimed

        if telegram_user_id:
            fields[MembersField.TELEGRAM_USER_ID] = str(telegram_user_id)
        elif not existing:
            fields[MembersField.TELEGRAM_USER_ID] = self._placeholder_telegram_id(
                whop_user_id
            )
        else:
            existing_tg = (existing.get("fields") or {}).get(
                MembersField.TELEGRAM_USER_ID
            )
            if not existing_tg or self._is_placeholder_telegram_id(str(existing_tg)):
                fields[MembersField.TELEGRAM_USER_ID] = self._placeholder_telegram_id(
                    whop_user_id
                )

        optional_keys = {
            MembersField.PHONE,
            MembersField.PLATFORM,
            MembersField.PLATFORM_USER_ID,
            MembersField.TELEGRAM_CLAIMED,
        }
        if existing:
            result = await self._run(table.update, existing["id"], fields)
        else:
            result = await self._run(table.create, fields)
        if result is None and any(k in fields for k in optional_keys):
            slim = {k: v for k, v in fields.items() if k not in optional_keys}
            if existing:
                return await self._run(table.update, existing["id"], slim)
            return await self._run(table.create, slim)
        return result

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
        phone: str | None = None,
        platform: str | None = None,
        platform_user_id: str | None = None,
        telegram_claimed: bool | None = None,
    ) -> Optional[dict]:
        """Create-or-update a Members row (Whop row when whop_user_id is set)."""
        if whop_user_id:
            claimed = True if telegram_claimed is None else telegram_claimed
            return await self.upsert_whop_member(
                whop_user_id=whop_user_id,
                whop_membership_id=whop_membership_id,
                plan=plan,
                status=status,
                join_date=join_date,
                email=email,
                name=name,
                phone=phone,
                telegram_user_id=telegram_user_id,
                telegram_username=telegram_username,
                telegram_claimed=claimed,
                platform=platform,
                platform_user_id=platform_user_id,
            )

        if not self.enabled:
            return None

        fields: dict[str, Any] = {
            MembersField.TELEGRAM_USER_ID: str(telegram_user_id),
        }
        if telegram_username:
            fields[MembersField.TELEGRAM_USERNAME] = telegram_username
        if name:
            fields[MembersField.NAME] = name
        if whop_membership_id:
            fields[MembersField.WHOP_MEMBERSHIP_ID] = whop_membership_id
        plan_value = self._plan_field(plan)
        if plan_value:
            fields[MembersField.PLAN] = plan_value
        if status is not None:
            fields[MembersField.STATUS] = (
                status.value if isinstance(status, MemberStatus) else str(status)
            )
        if join_date:
            fields[MembersField.JOIN_DATE] = join_date
        if email:
            fields[MembersField.EMAIL] = email
        if phone:
            fields[MembersField.PHONE] = phone
        platform_value = normalize_trading_platform(platform)
        if platform_value:
            fields[MembersField.PLATFORM] = platform_value
        if platform_user_id:
            fields[MembersField.PLATFORM_USER_ID] = platform_user_id.strip()
        if telegram_claimed is not None:
            fields[MembersField.TELEGRAM_CLAIMED] = telegram_claimed
        fields[MembersField.LAST_ACTIVITY] = datetime.now(timezone.utc).isoformat()

        table = self._table(settings.airtable_members_table)
        match_formula = match({MembersField.TELEGRAM_USER_ID: str(telegram_user_id)})

        existing = await self._run(table.first, formula=match_formula)
        optional_keys = {
            MembersField.PHONE,
            MembersField.PLATFORM,
            MembersField.PLATFORM_USER_ID,
            MembersField.TELEGRAM_CLAIMED,
        }
        if existing:
            result = await self._run(table.update, existing["id"], fields)
        else:
            result = await self._run(table.create, fields)
        if result is None and any(k in fields for k in optional_keys):
            slim = {k: v for k, v in fields.items() if k not in optional_keys}
            if existing:
                return await self._run(table.update, existing["id"], slim)
            return await self._run(table.create, slim)
        return result

    @staticmethod
    def _plan_field(plan: str | None) -> str | None:
        from integrations.plan_mapping import plan_for_airtable

        return plan_for_airtable(plan)

    @staticmethod
    def _is_expense_entry(entry_type: FinanceType | str | None) -> bool:
        if entry_type is None:
            return False
        value = entry_type.value if isinstance(entry_type, FinanceType) else str(entry_type)
        return value.strip().lower() == FinanceType.EXPENSE.value.lower()

    @staticmethod
    def _money_fields(
        *,
        amount: float,
        fees: float | None = None,
        net_amount: float | None = None,
        entry_type: FinanceType | str | None = None,
        amount_key: str = FinanceField.AMOUNT,
        fees_key: str = FinanceField.FEES,
        net_key: str = FinanceField.NET_AMOUNT,
    ) -> dict[str, float]:
        gross = float(amount)
        fee_val = float(fees) if fees is not None else 0.0
        net_val = float(net_amount) if net_amount is not None else gross - fee_val

        if AirtableClient._is_expense_entry(entry_type):
            gross = -abs(gross)
            fee_val = abs(fee_val)
            net_val = -abs(net_val) if net_val else gross
        else:
            gross = abs(gross)
            fee_val = abs(fee_val)
            if net_val == 0.0 and gross:
                net_val = gross - fee_val
            else:
                net_val = abs(net_val) if net_val else gross - fee_val

        return {
            amount_key: gross,
            fees_key: fee_val,
            net_key: net_val,
        }

    @staticmethod
    def _finance_line_amount(fields: dict[str, Any]) -> float:
        """Signed amount for P&L — expenses negative, payments positive."""
        if FinanceField.NET_AMOUNT in fields:
            return float(fields.get(FinanceField.NET_AMOUNT) or 0)
        return float(fields.get(FinanceField.AMOUNT) or 0)

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
        )

    async def mark_onboarding_complete(
        self,
        telegram_user_id: int,
        *,
        plan: str | None = None,
        phone: str | None = None,
        platform: str | None = None,
        platform_user_id: str | None = None,
        name: str | None = None,
        telegram_username: str | None = None,
    ) -> Optional[dict]:
        if not self.enabled:
            return None

        completed_at = datetime.now(timezone.utc).isoformat()
        fields: dict[str, Any] = {
            MembersField.ONBOARDING_COMPLETED: True,
            MembersField.ONBOARDING_COMPLETED_AT: completed_at,
            MembersField.STATUS: MemberStatus.ACTIVE.value,
            MembersField.TELEGRAM_CLAIMED: True,
            MembersField.LAST_ACTIVITY: completed_at,
        }
        plan_value = self._plan_field(plan)
        if plan_value:
            fields[MembersField.PLAN] = plan_value
        if name:
            fields[MembersField.NAME] = name.strip()
        if phone:
            fields[MembersField.PHONE] = phone
        platform_value = normalize_trading_platform(platform)
        if platform_value:
            fields[MembersField.PLATFORM] = platform_value
        if platform_user_id:
            fields[MembersField.PLATFORM_USER_ID] = platform_user_id.strip()

        table = self._table(settings.airtable_members_table)
        match_formula = match({MembersField.TELEGRAM_USER_ID: str(telegram_user_id)})
        existing = await self._run(table.first, formula=match_formula)
        if existing:
            return await self._run(table.update, existing["id"], fields)

        create_fields = {
            MembersField.TELEGRAM_USER_ID: str(telegram_user_id),
            **fields,
        }
        if telegram_username:
            create_fields[MembersField.TELEGRAM_USERNAME] = telegram_username
        return await self._run(table.create, create_fields)

    async def find_member_record_id(self, telegram_user_id: int) -> Optional[str]:
        if not self.enabled:
            return None
        table = self._table(settings.airtable_members_table)
        match_formula = match({MembersField.TELEGRAM_USER_ID: str(telegram_user_id)})
        rec = await self._run(table.first, formula=match_formula)
        return rec["id"] if rec else None

    # ---------- Finance (payments + expenses in one table) ----------

    @staticmethod
    def _finance_entry_id_field() -> str:
        """Support using the legacy ``Payments`` table as the unified finance table."""
        if (
            settings.airtable_finance_table.strip().lower()
            == settings.airtable_payments_table.strip().lower()
        ):
            return "Payment ID"
        return FinanceField.ENTRY_ID

    async def record_finance_entry(
        self,
        *,
        entry_id: str,
        entry_type: FinanceType | str,
        amount: float,
        currency: str,
        date_iso: str | None = None,
        telegram_user_id: int | None = None,
        fees: float | None = None,
        net_amount: float | None = None,
        whop_user_id: str | None = None,
        plan: str | None = None,
        status: PaymentStatus | str | None = None,
        category: ExpenseCategory | str | None = None,
        description: str | None = None,
        added_by: str | None = None,
        notes: str | None = None,
    ) -> Optional[dict]:
        if not self.enabled:
            return None

        type_value = (
            entry_type.value
            if isinstance(entry_type, FinanceType)
            else str(entry_type)
        )
        entry_id_field = self._finance_entry_id_field()
        money = self._money_fields(
            amount=amount,
            fees=fees,
            net_amount=net_amount,
            entry_type=type_value,
        )
        fields: dict[str, Any] = {
            entry_id_field: entry_id,
            FinanceField.TYPE: type_value,
            **money,
            FinanceField.CURRENCY: normalize_currency(currency),
            FinanceField.DATE: date_iso or datetime.now(timezone.utc).isoformat(),
        }
        plan_value = self._plan_field(plan)
        if plan_value:
            fields[FinanceField.PLAN] = plan_value
        if whop_user_id:
            fields[FinanceField.WHOP_USER_ID] = whop_user_id
        if status is not None:
            fields[FinanceField.STATUS] = (
                status.value if isinstance(status, PaymentStatus) else str(status)
            )
        if category is not None:
            fields[FinanceField.CATEGORY] = (
                category.value if isinstance(category, ExpenseCategory) else str(category)
            )
        if description:
            fields[FinanceField.DESCRIPTION] = description
        if added_by:
            fields[FinanceField.ADDED_BY] = added_by
        if notes:
            fields[FinanceField.NOTES] = notes

        if telegram_user_id is not None:
            member_rec_id = await self.find_member_record_id(telegram_user_id)
            if member_rec_id:
                fields[FinanceField.MEMBER] = [member_rec_id]

        table = self._table(settings.airtable_finance_table)
        existing = await self._run(
            table.first, formula=match({entry_id_field: entry_id})
        )
        if existing:
            result = await self._run(table.update, existing["id"], fields)
        else:
            result = await self._run(table.create, fields)
        if result is None:
            legacy = {
                entry_id_field: entry_id,
                FinanceField.AMOUNT: fields[FinanceField.AMOUNT],
                FinanceField.CURRENCY: fields[FinanceField.CURRENCY],
                FinanceField.DATE: fields[FinanceField.DATE],
            }
            if FinanceField.PLAN in fields:
                legacy[FinanceField.PLAN] = fields[FinanceField.PLAN]
            if FinanceField.WHOP_USER_ID in fields:
                legacy[FinanceField.WHOP_USER_ID] = fields[FinanceField.WHOP_USER_ID]
            if FinanceField.STATUS in fields:
                legacy[FinanceField.STATUS] = fields[FinanceField.STATUS]
            if FinanceField.MEMBER in fields:
                legacy[FinanceField.MEMBER] = fields[FinanceField.MEMBER]
            if existing:
                return await self._run(table.update, existing["id"], legacy)
            return await self._run(table.create, legacy)
        return result

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
        fees: float | None = None,
        net_amount: float | None = None,
    ) -> Optional[dict]:
        return await self.record_finance_entry(
            entry_id=payment_id,
            entry_type=FinanceType.PAYMENT,
            telegram_user_id=telegram_user_id,
            amount=amount,
            fees=fees,
            net_amount=net_amount,
            currency=currency,
            plan=plan,
            status=status,
            date_iso=date_iso,
            whop_user_id=whop_user_id,
            notes=notes,
        )

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
        fees: float | None = None,
        net_amount: float | None = None,
    ) -> Optional[dict]:
        entry_id = f"exp-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        return await self.record_finance_entry(
            entry_id=entry_id,
            entry_type=FinanceType.EXPENSE,
            amount=amount,
            fees=fees,
            net_amount=net_amount,
            currency=currency,
            category=category,
            description=description,
            added_by=added_by,
            date_iso=date_iso,
            notes=notes,
        )

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

        table = self._table(settings.airtable_finance_table)
        records = await self._run(table.all) or []

        totals: dict[str, float] = {}
        count = 0
        for r in records:
            f = r.get("fields", {})
            if f.get(FinanceField.TYPE) != FinanceType.PAYMENT.value:
                continue
            if f.get(FinanceField.STATUS) not in (
                None,
                PaymentStatus.SUCCEEDED.value,
            ):
                continue
            date_str = f.get(FinanceField.DATE)
            if date_str:
                try:
                    when = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if since and when < since:
                    continue
                if until and when > until:
                    continue
            currency = normalize_currency(f.get(FinanceField.CURRENCY))
            totals[currency] = totals.get(currency, 0.0) + self._finance_line_amount(f)
            count += 1

        return {"by_currency": totals, "count": count}

    async def expense_summary(
        self, since: datetime | None = None, until: datetime | None = None
    ) -> dict:
        if not self.enabled:
            return {"by_currency": {}, "by_category": {}, "count": 0}

        table = self._table(settings.airtable_finance_table)
        records = await self._run(table.all) or []

        by_currency: dict[str, float] = {}
        by_category: dict[str, float] = {}
        count = 0
        for r in records:
            f = r.get("fields", {})
            if f.get(FinanceField.TYPE) != FinanceType.EXPENSE.value:
                continue
            date_str = f.get(FinanceField.DATE)
            if date_str:
                try:
                    when = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if since and when < since:
                    continue
                if until and when > until:
                    continue
            currency = normalize_currency(f.get(FinanceField.CURRENCY))
            amount = abs(self._finance_line_amount(f))
            category = f.get(FinanceField.CATEGORY) or "Other"
            by_currency[currency] = by_currency.get(currency, 0.0) + amount
            by_category[category] = by_category.get(category, 0.0) + amount
            count += 1

        return {
            "by_currency": by_currency,
            "by_category": by_category,
            "count": count,
        }

    # ---------- Schema validation ----------

    @staticmethod
    def _required_schema_fields(short: str) -> list[str]:
        required = list(ALL_TABLES[short])
        if short == "finance":
            from airtable.schema_fields import finance_entry_id_field_name

            entry_name = finance_entry_id_field_name()
            required = [
                entry_name if field == FinanceField.ENTRY_ID else field
                for field in required
            ]
        return required

    async def validate_schema(self) -> dict:
        """Probe each configured table and confirm required fields exist."""
        if not self.enabled:
            return {"ok": False, "reason": "Airtable client not configured"}

        from airtable.schema_fields import field_is_present

        results: dict[str, dict] = {}
        table_map = {
            "members": settings.airtable_members_table,
            "finance": settings.airtable_finance_table,
            "checklist": settings.airtable_checklist_table,
        }

        base_schema = await self._run(self._base.schema)
        if base_schema is None:
            return {"ok": False, "reason": "Could not read Airtable base schema"}

        for short, table_name in table_map.items():
            required = self._required_schema_fields(short)
            try:
                table_schema = base_schema.table(table_name)
                present = {field.name for field in table_schema.fields}
                missing = [
                    field for field in required if not field_is_present(field, present)
                ]
                results[short] = {
                    "ok": not missing,
                    "table": table_name,
                    "missing": missing,
                }
            except KeyError:
                results[short] = {
                    "ok": False,
                    "table": table_name,
                    "error": f"Table '{table_name}' not found in base",
                }
            except Exception as e:
                results[short] = {
                    "ok": False,
                    "table": table_name,
                    "error": str(e)[:200],
                }

        results["all_ok"] = all(v.get("ok") for k, v in results.items() if k != "all_ok")
        return results
