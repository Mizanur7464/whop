"""
High-level sync orchestration.

Pure business logic that knows when and what to push to Airtable.
Whop event handlers and bot handlers call these functions — they
shouldn't talk to the Airtable client directly.

All functions are best-effort: if Airtable is unconfigured or
unreachable, they log and return without raising. This keeps the
Telegram side fully functional even when Airtable is down.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from airtable.client import AirtableClient
from airtable.schema import MemberStatus, MembersField, PaymentStatus


_client: Optional[AirtableClient] = None


def client() -> AirtableClient:
    """Lazy singleton — created on first use."""
    global _client
    if _client is None:
        _client = AirtableClient()
    return _client


def _linked_whop(telegram_user_id: int) -> dict:
    """Whop IDs from local storage so Airtable upserts match the same row."""
    from bot import storage

    user = storage.get_user(telegram_user_id) or {}
    return {
        "whop_user_id": user.get("whop_user_id"),
        "whop_membership_id": user.get("whop_membership_id"),
        "plan": user.get("plan"),
    }


def _email_from_user(user: dict, fallback: str | None = None) -> str | None:
    for key in ("checkout_email", "contact_email", "email"):
        raw = (user.get(key) or "").strip().lower()
        if raw and "@" in raw:
            return raw
    if fallback and "@" in fallback:
        return fallback.strip().lower()
    return None


def _name_from_user(user: dict) -> str | None:
    full = (user.get("contact_full_name") or "").strip()
    if full:
        return full
    parts = [
        (user.get("contact_first_name") or "").strip(),
        (user.get("contact_last_name") or "").strip(),
    ]
    joined = " ".join(p for p in parts if p).strip()
    if joined:
        return joined
    parts = [
        (user.get("first_name") or "").strip(),
        (user.get("last_name") or "").strip(),
    ]
    return " ".join(p for p in parts if p).strip() or None


# ---------- Member lifecycle ----------

async def member_joined(
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    name: str | None,
    whop_user_id: str | None,
    whop_membership_id: str | None,
    plan: str | None,
    email: str | None = None,
) -> None:
    """Called when a user successfully claims their Whop purchase."""
    c = client()
    if not c.enabled:
        return
    try:
        if whop_user_id:
            await c.upsert_whop_member(
                whop_user_id=whop_user_id,
                whop_membership_id=whop_membership_id,
                plan=plan,
                status=MemberStatus.ACTIVE,
                join_date=datetime.now(timezone.utc).isoformat(),
                email=email,
                name=name,
                telegram_user_id=telegram_user_id,
                telegram_username=telegram_username,
                telegram_claimed=True,
            )
        else:
            await c.upsert_member(
                telegram_user_id=telegram_user_id,
                telegram_username=telegram_username,
                name=name,
                whop_membership_id=whop_membership_id,
                plan=plan,
                status=MemberStatus.ACTIVE,
                join_date=datetime.now(timezone.utc).isoformat(),
                email=email,
                telegram_claimed=True,
            )
        logger.info(
            f"Airtable: member_joined tg={telegram_user_id} plan={plan} email={email!r}"
        )
    except Exception as e:
        logger.warning(f"Airtable member_joined failed: {e}")


async def member_rejoined(
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    name: str | None,
    whop_user_id: str | None,
    whop_membership_id: str | None,
    plan: str | None,
    email: str | None = None,
) -> None:
    """Returning member after Whop cancel — reset CRM onboarding, Status=Pending."""
    c = client()
    if not c.enabled:
        return
    try:
        await c.reactivate_member_for_onboarding(
            telegram_user_id=telegram_user_id,
            whop_user_id=whop_user_id,
            whop_membership_id=whop_membership_id,
            plan=plan,
            email=email,
            name=name,
            telegram_username=telegram_username,
        )
        logger.info(
            f"Airtable: member_rejoined tg={telegram_user_id} plan={plan} "
            f"membership={whop_membership_id!r}"
        )
    except Exception as e:
        logger.warning(f"Airtable member_rejoined failed: {e}")


async def sync_whop_membership(
    *,
    whop_user_id: str,
    whop_membership_id: str | None = None,
    plan: str | None = None,
    email: str | None = None,
    name: str | None = None,
    phone: str | None = None,
    join_date: str | None = None,
    telegram_user_id: int | None = None,
    telegram_username: str | None = None,
    telegram_claimed: bool = False,
    status: MemberStatus | str = MemberStatus.ACTIVE,
    platform: str | None = None,
    platform_user_id: str | None = None,
) -> None:
    """Upsert a Whop member into Airtable (claimed or awaiting Telegram /claim)."""
    c = client()
    if not c.enabled:
        return
    try:
        await c.upsert_whop_member(
            whop_user_id=whop_user_id,
            whop_membership_id=whop_membership_id,
            plan=plan,
            email=email,
            name=name,
            phone=phone,
            join_date=join_date or datetime.now(timezone.utc).isoformat(),
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            telegram_claimed=telegram_claimed,
            status=status,
            platform=platform,
            platform_user_id=platform_user_id,
        )
        if platform and platform_user_id:
            await c.link_member_to_platform_client(
                telegram_user_id=telegram_user_id,
                whop_user_id=whop_user_id,
                platform=platform,
                platform_user_id=platform_user_id,
            )
        logger.info(
            f"Airtable: whop sync whop={whop_user_id} claimed={telegram_claimed}"
        )
    except Exception as e:
        logger.warning(f"Airtable sync_whop_membership failed: {e}")


async def whop_membership_ended(whop_user_id: str) -> None:
    """Mark an Airtable row expired when Whop membership ends (linked or not)."""
    c = client()
    if not c.enabled:
        return
    try:
        tg_id = None
        from bot import storage

        tg_id = storage.get_telegram_id_for_whop_user(whop_user_id)
        if tg_id is not None:
            await c._set_member_status_with_onboarding_reset(
                telegram_user_id=tg_id,
                whop_user_id=whop_user_id,
                status=MemberStatus.EXPIRED,
            )
        else:
            await c._set_member_status_with_onboarding_reset(
                whop_user_id=whop_user_id,
                status=MemberStatus.EXPIRED,
            )
        logger.info(f"Airtable: whop membership ended whop={whop_user_id}")
    except Exception as e:
        logger.warning(f"Airtable whop_membership_ended failed: {e}")


async def member_status_changed(telegram_user_id: int, status: str) -> None:
    """Called on ban/unban/expire."""
    c = client()
    if not c.enabled:
        return

    # Normalize free-form status strings into the canonical enum
    mapping = {
        "active": MemberStatus.ACTIVE,
        "expired": MemberStatus.EXPIRED,
        "banned": MemberStatus.BANNED,
        "pending": MemberStatus.PENDING,
        "left": MemberStatus.LEFT,
    }
    canonical = mapping.get(status.lower(), MemberStatus.PENDING)

    try:
        await c.update_member_status(
            telegram_user_id,
            canonical,
            whop_user_id=_linked_whop(telegram_user_id).get("whop_user_id"),
            clear_onboarding_completed=canonical
            in (MemberStatus.EXPIRED, MemberStatus.LEFT),
        )
        logger.info(f"Airtable: status tg={telegram_user_id} -> {canonical.value}")
    except Exception as e:
        logger.warning(f"Airtable member_status_changed failed: {e}")


async def terms_accepted(
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    name: str | None,
    accepted_at_iso: str,
) -> None:
    c = client()
    if not c.enabled:
        return
    try:
        linked = _linked_whop(telegram_user_id)
        await c.record_terms_accepted(
            telegram_user_id,
            telegram_username=telegram_username,
            name=name,
            accepted_at_iso=accepted_at_iso,
            whop_user_id=linked.get("whop_user_id"),
        )
        logger.info(f"Airtable: terms accepted tg={telegram_user_id}")
    except Exception as e:
        logger.warning(f"Airtable terms_accepted failed: {e}")


async def onboarding_completed(
    telegram_user_id: int,
    *,
    plan: str | None = None,
    phone: str | None = None,
    platform: str | None = None,
    platform_user_id: str | None = None,
    name: str | None = None,
) -> bool:
    """Mark onboarding complete in CRM. Returns True when checkbox is confirmed set."""
    c = client()
    if not c.enabled:
        logger.warning(
            f"Airtable disabled — onboarding checkbox not updated tg={telegram_user_id}"
        )
        return False

    from bot import storage

    linked = _linked_whop(telegram_user_id)
    user = storage.get_user(telegram_user_id) or {}
    last_err = "unknown"
    for attempt in range(1, 4):
        try:
            result = await c.mark_onboarding_complete(
                telegram_user_id,
                plan=plan or linked.get("plan"),
                phone=phone,
                platform=platform,
                platform_user_id=platform_user_id,
                name=name,
                telegram_username=user.get("username"),
                whop_user_id=linked.get("whop_user_id"),
            )
            if result and (result.get("fields") or {}).get(
                MembersField.ONBOARDING_COMPLETED
            ):
                plat = platform or user.get("platform")
                pid = platform_user_id or user.get("platform_user_id")
                if plat and pid:
                    await c.link_member_to_platform_client(
                        telegram_user_id=telegram_user_id,
                        whop_user_id=linked.get("whop_user_id"),
                        platform=plat,
                        platform_user_id=str(pid),
                    )
                logger.info(f"Airtable: onboarding done tg={telegram_user_id}")
                return True
            last_err = "checkbox not set on Airtable row"
            logger.warning(
                f"Airtable onboarding_completed attempt {attempt}/3: {last_err} "
                f"tg={telegram_user_id}"
            )
        except Exception as e:
            last_err = str(e)
            logger.warning(
                f"Airtable onboarding_completed attempt {attempt}/3 tg={telegram_user_id}: {e}"
            )
        if attempt < 3:
            await asyncio.sleep(attempt)

    logger.error(
        f"Airtable onboarding_completed failed tg={telegram_user_id}: {last_err}"
    )
    return False


async def backfill_onboarding_completed_in_crm() -> dict[str, int]:
    """Re-sync Onboarding Completed checkbox for all locally approved users."""
    from bot import storage

    ok = 0
    failed = 0
    for user_id in storage.list_onboarding_approved_user_ids():
        record = storage.get_user(user_id) or {}
        success = await onboarding_completed(
            user_id,
            plan=record.get("plan"),
            phone=record.get("contact_phone"),
            platform=record.get("platform"),
            platform_user_id=record.get("platform_user_id"),
            name=" ".join(
                p
                for p in [
                    record.get("contact_first_name"),
                    record.get("contact_last_name"),
                ]
                if p
            ).strip()
            or None,
        )
        if success:
            ok += 1
        else:
            failed += 1
    return {"ok": ok, "failed": failed}


async def reconcile_members_table() -> dict[str, int]:
    """Merge/delete duplicate rows in the Members table."""
    c = client()
    if not c.enabled:
        return {"groups_merged": 0, "rows_before": 0, "rows_after": 0}
    try:
        return await c.reconcile_duplicate_members()
    except Exception as e:
        logger.warning(f"Airtable reconcile_members_table failed: {e}")
        return {"groups_merged": 0, "rows_before": 0, "rows_after": 0}


# ---------- Checklist activity ----------

async def checklist_item_toggled(
    *,
    telegram_user_id: int,
    task_id: str,
    task_title: str,
    completed: bool,
) -> None:
    c = client()
    if not c.enabled:
        return
    try:
        await c.record_checklist_event(
            telegram_user_id=telegram_user_id,
            task_id=task_id,
            task_title=task_title,
            completed=completed,
        )
    except Exception as e:
        logger.warning(f"Airtable checklist_item_toggled failed: {e}")


async def copytrading_checklist_toggled(
    *,
    telegram_user_id: int,
    task_id: str,
    task_title: str,
    completed: bool,
) -> None:
    await checklist_item_toggled(
        telegram_user_id=telegram_user_id,
        task_id=f"ct:{task_id}",
        task_title=f"[Copy trading] {task_title}",
        completed=completed,
    )


async def copytrading_completed(
    telegram_user_id: int,
    *,
    platform: str | None = None,
    telegram_username: str | None = None,
    name: str | None = None,
) -> None:
    c = client()
    if not c.enabled:
        return
    when = datetime.now(timezone.utc).isoformat()
    plat = f" ({platform})" if platform else ""
    note = f"Copy trading setup completed{plat} at {when}"
    try:
        linked = _linked_whop(telegram_user_id)
        await c.append_member_note(
            telegram_user_id,
            note,
            telegram_username=telegram_username,
            name=name,
            whop_user_id=linked.get("whop_user_id"),
        )
        logger.info(f"Airtable: copy trading done tg={telegram_user_id}")
    except Exception as e:
        logger.warning(f"Airtable copytrading_completed failed: {e}")


async def member_platform_selected(
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    name: str | None,
    platform: str,
) -> None:
    c = client()
    if not c.enabled:
        return
    try:
        linked = _linked_whop(telegram_user_id)
        await c.upsert_member(
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            name=name,
            platform=platform,
            whop_user_id=linked.get("whop_user_id"),
            whop_membership_id=linked.get("whop_membership_id"),
            plan=linked.get("plan"),
        )
        from bot import storage

        user = storage.get_user(telegram_user_id) or {}
        pid = user.get("platform_user_id")
        if pid:
            await c.link_member_to_platform_client(
                telegram_user_id=telegram_user_id,
                whop_user_id=linked.get("whop_user_id"),
                platform=platform,
                platform_user_id=str(pid),
            )
        logger.info(f"Airtable: platform={platform!r} tg={telegram_user_id}")
    except Exception as e:
        logger.warning(f"Airtable member_platform_selected failed: {e}")


async def member_contact_collected(
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    name: str | None,
    email: str,
    phone: str,
    platform: str | None = None,
    platform_user_id: str | None = None,
) -> None:
    c = client()
    if not c.enabled:
        return
    try:
        linked = _linked_whop(telegram_user_id)
        await c.upsert_member(
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            name=name,
            email=email,
            phone=phone,
            platform=platform,
            platform_user_id=platform_user_id,
            whop_user_id=linked.get("whop_user_id"),
            whop_membership_id=linked.get("whop_membership_id"),
            plan=linked.get("plan"),
        )
        if platform and platform_user_id:
            await c.link_member_to_platform_client(
                telegram_user_id=telegram_user_id,
                whop_user_id=linked.get("whop_user_id"),
                platform=platform,
                platform_user_id=platform_user_id,
            )
        logger.info(
            f"Airtable: contact saved tg={telegram_user_id} "
            f"platform={platform!r} platform_user_id={platform_user_id!r}"
        )
    except Exception as e:
        logger.warning(f"Airtable member_contact_collected failed: {e}")


async def member_left_telegram(
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    name: str | None,
    left_at_iso: str,
    group_name: str | None = None,
) -> None:
    """User left a monitored Telegram group — set Status=Left (Whop may still be active)."""
    c = client()
    if not c.enabled:
        return
    where = group_name or "group"
    note = f"Left {where} at {left_at_iso} (Telegram group)"
    try:
        linked = _linked_whop(telegram_user_id)
        extra: dict = {}
        if telegram_username:
            extra[MembersField.TELEGRAM_USERNAME] = telegram_username
        if name:
            extra[MembersField.NAME] = name
        await c._set_member_status_with_onboarding_reset(
            telegram_user_id=telegram_user_id,
            whop_user_id=linked.get("whop_user_id"),
            status=MemberStatus.LEFT,
            extra_fields=extra or None,
        )
        await c.append_member_note(
            telegram_user_id,
            note,
            telegram_username=telegram_username,
            name=name,
            whop_user_id=linked.get("whop_user_id"),
        )
        logger.info(
            f"Airtable: telegram left tg={telegram_user_id} group={where!r}"
        )
    except Exception as e:
        logger.warning(f"Airtable member_left_telegram failed: {e}")


async def member_left_group(
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    name: str | None,
    reason: str,
    left_at_iso: str,
    group_name: str | None = None,
) -> None:
    """User submitted a leave reason after the leave survey DM."""
    c = client()
    if not c.enabled:
        return
    where = group_name or "group"
    note = f"Leave reason ({where}): {reason}"
    try:
        linked = _linked_whop(telegram_user_id)
        await c.append_member_note(
            telegram_user_id,
            note,
            telegram_username=telegram_username,
            name=name,
            whop_user_id=linked.get("whop_user_id"),
        )
        logger.info(f"Airtable: leave reason tg={telegram_user_id} reason={reason!r}")
    except Exception as e:
        logger.warning(f"Airtable member_left_group failed: {e}")


async def support_submitted(
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    name: str | None,
    summary: str,
) -> None:
    c = client()
    if not c.enabled:
        return
    when = datetime.now(timezone.utc).isoformat()
    note = f"Support form submitted at {when}\n{summary}"
    try:
        linked = _linked_whop(telegram_user_id)
        await c.append_member_note(
            telegram_user_id,
            note,
            telegram_username=telegram_username,
            name=name,
            whop_user_id=linked.get("whop_user_id"),
        )
        logger.info(f"Airtable: support submitted tg={telegram_user_id}")
    except Exception as e:
        logger.warning(f"Airtable support_submitted failed: {e}")


# ---------- Payments ----------

async def payment_recorded(
    *,
    payment_id: str,
    telegram_user_id: int | None,
    whop_user_id: str | None,
    amount: float,
    currency: str,
    plan: str | None,
    status: str = "succeeded",
    notes: str | None = None,
    fees: float | None = None,
    net_amount: float | None = None,
    category: str | None = None,
    email: str | None = None,
    date_iso: str | None = None,
) -> None:
    c = client()
    if not c.enabled:
        return

    mapping = {
        "succeeded": PaymentStatus.SUCCEEDED,
        "failed": PaymentStatus.FAILED,
        "refunded": PaymentStatus.REFUNDED,
    }
    canonical = mapping.get(status.lower(), PaymentStatus.SUCCEEDED)

    try:
        result = await c.record_payment(
            payment_id=payment_id,
            telegram_user_id=telegram_user_id,
            whop_user_id=whop_user_id,
            email=email,
            amount=amount,
            fees=fees,
            net_amount=net_amount,
            currency=currency,
            plan=plan,
            status=canonical,
            notes=notes,
            category=category,
            date_iso=date_iso,
        )
        if result is None:
            logger.error(
                f"Airtable payment_recorded failed (no row saved): id={payment_id} "
                f"amount={amount} {currency}"
            )
        else:
            logger.info(
                f"Airtable: payment {payment_id} {amount} {currency} ({canonical.value})"
            )
    except Exception as e:
        logger.warning(f"Airtable payment_recorded failed: {e}")


async def backfill_members_crm_from_storage() -> dict[str, int]:
    """Push locally stored member fields (email, plan, platform UID) to Airtable."""
    from bot import storage

    c = client()
    if not c.enabled:
        return {"updated": 0, "linked_clients": 0, "skipped": 0, "failed": 0}

    updated = linked_clients = skipped = failed = 0
    for user_id in storage.list_all_user_ids():
        user = storage.get_user(user_id) or {}
        whop_user_id = user.get("whop_user_id")
        if not whop_user_id and not user.get("platform_user_id"):
            skipped += 1
            continue

        email = _email_from_user(user)
        try:
            await c.upsert_member(
                telegram_user_id=user_id,
                telegram_username=user.get("username"),
                name=_name_from_user(user),
                whop_user_id=whop_user_id,
                whop_membership_id=user.get("whop_membership_id"),
                plan=user.get("plan"),
                email=email,
                phone=user.get("contact_phone"),
                platform=user.get("platform"),
                platform_user_id=user.get("platform_user_id"),
                telegram_claimed=bool(whop_user_id),
            )
            updated += 1
            if user.get("platform") and user.get("platform_user_id"):
                if await c.link_member_to_platform_client(
                    telegram_user_id=user_id,
                    whop_user_id=whop_user_id,
                    platform=user.get("platform"),
                    platform_user_id=user.get("platform_user_id"),
                ):
                    linked_clients += 1
        except Exception as e:
            logger.warning(f"Airtable backfill member tg={user_id} failed: {e}")
            failed += 1

    return {
        "updated": updated,
        "linked_clients": linked_clients,
        "skipped": skipped,
        "failed": failed,
    }


async def link_all_platform_clients() -> dict[str, int]:
    """Backfill Vantage/Premier client links for all Members rows."""
    c = client()
    if not c.enabled:
        return {"linked": 0, "missing_client": 0, "skipped": 0, "failed": 0}
    try:
        return await c.backfill_platform_client_links()
    except Exception as e:
        logger.warning(f"Airtable link_all_platform_clients failed: {e}")
        return {"linked": 0, "missing_client": 0, "skipped": 0, "failed": 0}
