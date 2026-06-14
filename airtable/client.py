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
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

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

_MEMBER_UPSERT_LOCKS: dict[str, asyncio.Lock] = {}
_MEMBER_UPSERT_GUARD = asyncio.Lock()


@asynccontextmanager
async def member_upsert_lock(
    *,
    telegram_user_id: int | None = None,
    whop_user_id: str | None = None,
) -> AsyncIterator[None]:
    """Serialize Airtable member upserts for the same person (prevents duplicate rows)."""
    parts: list[str] = []
    if telegram_user_id is not None:
        parts.append(f"tg:{telegram_user_id}")
    if whop_user_id:
        parts.append(f"whop:{whop_user_id}")
    key = "|".join(parts) if parts else "member:unknown"
    async with _MEMBER_UPSERT_GUARD:
        lock = _MEMBER_UPSERT_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        yield


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

    @staticmethod
    def _member_row_score(rec: dict) -> int:
        """Prefer the most complete row when merging duplicates."""
        fields = rec.get("fields") or {}
        score = 0
        tg = fields.get(MembersField.TELEGRAM_USER_ID)
        if tg and not AirtableClient._is_placeholder_telegram_id(str(tg)):
            score += 100
        elif tg:
            score += 20
        if fields.get(MembersField.WHOP_USER_ID):
            score += 50
        if fields.get(MembersField.EMAIL):
            score += 15
        if fields.get(MembersField.PHONE):
            score += 10
        if fields.get(MembersField.PLATFORM_USER_ID):
            score += 10
        if fields.get(MembersField.ONBOARDING_COMPLETED):
            score += 25
        if fields.get(MembersField.TELEGRAM_CLAIMED):
            score += 10
        for key in (
            MembersField.NAME,
            MembersField.PLAN,
            MembersField.PLATFORM,
            MembersField.JOIN_DATE,
        ):
            if fields.get(key):
                score += 2
        return score

    def _merge_member_field_sets(
        self,
        field_sets: list[dict[str, Any]],
        *,
        telegram_user_id: int | None = None,
        whop_user_id: str | None = None,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        notes: list[str] = []

        for fields in field_sets:
            for key, val in fields.items():
                if val is None or val == "":
                    continue
                if key == MembersField.NOTES:
                    notes.append(str(val).strip())
                    continue
                if key == MembersField.ONBOARDING_COMPLETED:
                    merged[key] = bool(merged.get(key)) or bool(val)
                    continue
                if key == MembersField.TELEGRAM_CLAIMED:
                    merged[key] = bool(merged.get(key)) or bool(val)
                    continue
                if key == MembersField.TELEGRAM_USER_ID:
                    if val and not self._is_placeholder_telegram_id(str(val)):
                        merged[key] = str(val)
                    elif key not in merged:
                        merged[key] = val
                    continue
                if key not in merged or merged[key] in ("", None):
                    merged[key] = val

        if notes:
            merged[MembersField.NOTES] = "\n".join(dict.fromkeys(notes))

        if telegram_user_id:
            merged[MembersField.TELEGRAM_USER_ID] = str(telegram_user_id)
        elif whop_user_id and (
            MembersField.TELEGRAM_USER_ID not in merged
            or not merged.get(MembersField.TELEGRAM_USER_ID)
            or self._is_placeholder_telegram_id(
                str(merged.get(MembersField.TELEGRAM_USER_ID))
            )
        ):
            merged[MembersField.TELEGRAM_USER_ID] = self._placeholder_telegram_id(
                whop_user_id
            )

        if whop_user_id:
            merged[MembersField.WHOP_USER_ID] = whop_user_id

        return merged

    async def _collect_member_rows(
        self,
        *,
        telegram_user_id: int | None = None,
        whop_user_id: str | None = None,
        platform_user_id: str | None = None,
    ) -> list[dict]:
        table = self._table(settings.airtable_members_table)
        seen: dict[str, dict] = {}

        if telegram_user_id is not None:
            formula = match({MembersField.TELEGRAM_USER_ID: str(telegram_user_id)})
            for rec in await self._run(table.all, formula=formula) or []:
                seen[rec["id"]] = rec

        if whop_user_id:
            for formula in (
                match({MembersField.WHOP_USER_ID: whop_user_id}),
                match(
                    {
                        MembersField.TELEGRAM_USER_ID: self._placeholder_telegram_id(
                            whop_user_id
                        )
                    }
                ),
            ):
                for rec in await self._run(table.all, formula=formula) or []:
                    seen[rec["id"]] = rec

        pid = (platform_user_id or "").strip()
        if pid:
            formula = match({MembersField.PLATFORM_USER_ID: pid})
            for rec in await self._run(table.all, formula=formula) or []:
                seen[rec["id"]] = rec

        return list(seen.values())

    async def consolidate_member_rows(
        self,
        *,
        telegram_user_id: int | None = None,
        whop_user_id: str | None = None,
        platform_user_id: str | None = None,
    ) -> Optional[dict]:
        """Merge duplicate member rows and delete extras."""
        if not self.enabled:
            return None

        records = await self._collect_member_rows(
            telegram_user_id=telegram_user_id,
            whop_user_id=whop_user_id,
            platform_user_id=platform_user_id,
        )
        if not records:
            return None
        if len(records) == 1:
            return records[0]

        table = self._table(settings.airtable_members_table)
        canonical = max(records, key=self._member_row_score)
        merged_fields = self._merge_member_field_sets(
            [rec.get("fields") or {} for rec in records],
            telegram_user_id=telegram_user_id,
            whop_user_id=whop_user_id,
        )
        result = await self._run(table.update, canonical["id"], merged_fields)

        for rec in records:
            if rec["id"] == canonical["id"]:
                continue
            deleted = await self._run(table.delete, rec["id"])
            if deleted is not None:
                logger.info(
                    f"Airtable: deleted duplicate member row {rec['id']} "
                    f"(kept {canonical['id']})"
                )

        return result or {**canonical, "fields": merged_fields}

    async def reconcile_duplicate_members(self) -> dict[str, int]:
        """Scan the Members table and merge/delete duplicate rows."""
        if not self.enabled:
            return {"groups_merged": 0, "rows_before": 0, "rows_after": 0}

        table = self._table(settings.airtable_members_table)
        records = await self._run(table.all) or []
        rows_before = len(records)

        telegram_ids: set[int] = set()
        whop_ids: set[str] = set()
        platform_ids: set[str] = set()

        for rec in records:
            fields = rec.get("fields") or {}
            tg_raw = fields.get(MembersField.TELEGRAM_USER_ID)
            if tg_raw and not self._is_placeholder_telegram_id(str(tg_raw)):
                try:
                    telegram_ids.add(int(str(tg_raw).strip()))
                except ValueError:
                    pass
            whop = fields.get(MembersField.WHOP_USER_ID)
            if whop:
                whop_ids.add(str(whop).strip())
            pid = fields.get(MembersField.PLATFORM_USER_ID)
            if pid:
                platform_ids.add(str(pid).strip())

        groups_merged = 0
        for tg in telegram_ids:
            rows = await self._collect_member_rows(telegram_user_id=tg)
            if len(rows) > 1:
                await self.consolidate_member_rows(telegram_user_id=tg)
                groups_merged += 1

        for whop in whop_ids:
            rows = await self._collect_member_rows(whop_user_id=whop)
            if len(rows) > 1:
                await self.consolidate_member_rows(whop_user_id=whop)
                groups_merged += 1

        for pid in platform_ids:
            rows = await self._collect_member_rows(platform_user_id=pid)
            if len(rows) > 1:
                await self.consolidate_member_rows(platform_user_id=pid)
                groups_merged += 1

        rows_after = len(await self._run(table.all) or [])
        logger.info(
            f"Airtable reconcile: merged {groups_merged} groups, "
            f"{rows_before} -> {rows_after} rows"
        )
        return {
            "groups_merged": groups_merged,
            "rows_before": rows_before,
            "rows_after": rows_after,
        }

    async def find_member_by_whop_user_id(self, whop_user_id: str) -> Optional[dict]:
        return await self.consolidate_member_rows(whop_user_id=whop_user_id)

    async def find_member_for_telegram(
        self,
        telegram_user_id: int,
        *,
        whop_user_id: str | None = None,
        platform_user_id: str | None = None,
    ) -> Optional[dict]:
        """Find (and merge) member rows by Telegram ID, Whop ID, or platform user ID."""
        return await self.consolidate_member_rows(
            telegram_user_id=telegram_user_id,
            whop_user_id=whop_user_id,
            platform_user_id=platform_user_id,
        )

    async def _upsert_member_fields(
        self,
        *,
        existing: Optional[dict],
        fields: dict[str, Any],
        match_formula: dict,
        optional_keys: set[str],
        telegram_user_id: int | None = None,
        whop_user_id: str | None = None,
        platform_user_id: str | None = None,
    ) -> Optional[dict]:
        """Update or create a row; avoid duplicate creates on optional-field failures."""
        table = self._table(settings.airtable_members_table)
        if existing:
            result = await self._run(table.update, existing["id"], fields)
        else:
            recheck = await self.consolidate_member_rows(
                telegram_user_id=telegram_user_id,
                whop_user_id=whop_user_id,
                platform_user_id=platform_user_id,
            )
            if recheck:
                result = await self._run(table.update, recheck["id"], fields)
            else:
                result = await self._run(table.create, fields)
        if result is None and any(k in fields for k in optional_keys):
            slim = {k: v for k, v in fields.items() if k not in optional_keys}
            if not existing:
                existing = await self._run(table.first, formula=match_formula)
                if not existing:
                    existing = await self.consolidate_member_rows(
                        telegram_user_id=telegram_user_id,
                        whop_user_id=whop_user_id,
                        platform_user_id=platform_user_id,
                    )
            if existing:
                return await self._run(table.update, existing["id"], slim)
            return await self._run(table.create, slim)
        return result

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

        async with member_upsert_lock(
            telegram_user_id=telegram_user_id,
            whop_user_id=whop_user_id,
        ):
            existing = await self.consolidate_member_rows(
                telegram_user_id=telegram_user_id,
                whop_user_id=whop_user_id,
                platform_user_id=platform_user_id,
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
                if not existing_tg or self._is_placeholder_telegram_id(
                    str(existing_tg)
                ):
                    fields[MembersField.TELEGRAM_USER_ID] = (
                        self._placeholder_telegram_id(whop_user_id)
                    )

            optional_keys = {
                MembersField.PHONE,
                MembersField.PLATFORM,
                MembersField.PLATFORM_USER_ID,
                MembersField.TELEGRAM_CLAIMED,
            }
            whop_match = match({MembersField.WHOP_USER_ID: whop_user_id})
            return await self._upsert_member_fields(
                existing=existing,
                fields=fields,
                match_formula=whop_match,
                optional_keys=optional_keys,
                telegram_user_id=telegram_user_id,
                whop_user_id=whop_user_id,
                platform_user_id=platform_user_id,
            )

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

        async with member_upsert_lock(telegram_user_id=telegram_user_id):
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

            match_formula = match(
                {MembersField.TELEGRAM_USER_ID: str(telegram_user_id)}
            )
            existing = await self.consolidate_member_rows(
                telegram_user_id=telegram_user_id,
                platform_user_id=platform_user_id,
            )
            optional_keys = {
                MembersField.PHONE,
                MembersField.PLATFORM,
                MembersField.PLATFORM_USER_ID,
                MembersField.TELEGRAM_CLAIMED,
            }
            return await self._upsert_member_fields(
                existing=existing,
                fields=fields,
                match_formula=match_formula,
                optional_keys=optional_keys,
                telegram_user_id=telegram_user_id,
                platform_user_id=platform_user_id,
            )

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
        self,
        telegram_user_id: int,
        status: MemberStatus | str,
        *,
        whop_user_id: str | None = None,
    ) -> Optional[dict]:
        if not self.enabled:
            return None
        return await self.upsert_member(
            telegram_user_id=telegram_user_id,
            status=status,
            whop_user_id=whop_user_id,
        )

    async def append_member_note(
        self,
        telegram_user_id: int,
        note: str,
        *,
        telegram_username: str | None = None,
        name: str | None = None,
        status: MemberStatus | str | None = None,
        whop_user_id: str | None = None,
        platform_user_id: str | None = None,
    ) -> Optional[dict]:
        """Append a line to the member Notes field (creates row if missing)."""
        if not self.enabled:
            return None
        await self.upsert_member(
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            name=name,
            status=status,
            whop_user_id=whop_user_id,
            platform_user_id=platform_user_id,
        )
        existing = await self.find_member_for_telegram(
            telegram_user_id,
            whop_user_id=whop_user_id,
            platform_user_id=platform_user_id,
        )
        if not existing:
            return None
        prev = (existing.get("fields") or {}).get(MembersField.NOTES) or ""
        merged = f"{prev}\n{note}".strip() if prev else note
        fields = {
            MembersField.NOTES: merged,
            MembersField.LAST_ACTIVITY: datetime.now(timezone.utc).isoformat(),
        }
        table = self._table(settings.airtable_members_table)
        return await self._run(table.update, existing["id"], fields)

    async def record_terms_accepted(
        self,
        telegram_user_id: int,
        *,
        telegram_username: str | None = None,
        name: str | None = None,
        accepted_at_iso: str,
        whop_user_id: str | None = None,
    ) -> Optional[dict]:
        """Log T&C acceptance on the member row (Notes + ensure row exists)."""
        return await self.append_member_note(
            telegram_user_id,
            f"T&C accepted at {accepted_at_iso}",
            telegram_username=telegram_username,
            name=name,
            whop_user_id=whop_user_id,
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
        whop_user_id: str | None = None,
    ) -> Optional[dict]:
        if not self.enabled:
            return None

        completed_at = datetime.now(timezone.utc).isoformat()
        fields: dict[str, Any] = {
            MembersField.TELEGRAM_USER_ID: str(telegram_user_id),
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
        if telegram_username:
            fields[MembersField.TELEGRAM_USERNAME] = telegram_username

        async with member_upsert_lock(
            telegram_user_id=telegram_user_id,
            whop_user_id=whop_user_id,
        ):
            table = self._table(settings.airtable_members_table)
            existing = await self.consolidate_member_rows(
                telegram_user_id=telegram_user_id,
                whop_user_id=whop_user_id,
                platform_user_id=platform_user_id,
            )
            if existing:
                return await self._run(table.update, existing["id"], fields)
            return await self._run(table.create, fields)

    async def find_member_record_id(
        self, telegram_user_id: int, *, whop_user_id: str | None = None
    ) -> Optional[str]:
        if not self.enabled:
            return None
        rec = await self.find_member_for_telegram(
            telegram_user_id, whop_user_id=whop_user_id
        )
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
