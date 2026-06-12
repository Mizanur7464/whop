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

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from airtable.client import AirtableClient
from airtable.schema import MemberStatus, PaymentStatus


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
        await c.upsert_whop_member(
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
    }
    canonical = mapping.get(status.lower(), MemberStatus.PENDING)

    try:
        await c.update_member_status(
            telegram_user_id,
            canonical,
            whop_user_id=_linked_whop(telegram_user_id).get("whop_user_id"),
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
) -> None:
    c = client()
    if not c.enabled:
        return
    try:
        linked = _linked_whop(telegram_user_id)
        await c.mark_onboarding_complete(
            telegram_user_id,
            plan=plan or linked.get("plan"),
            phone=phone,
            platform=platform,
            platform_user_id=platform_user_id,
            name=name,
            whop_user_id=linked.get("whop_user_id"),
        )
        logger.info(f"Airtable: onboarding done tg={telegram_user_id}")
    except Exception as e:
        logger.warning(f"Airtable onboarding_completed failed: {e}")


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
        logger.info(
            f"Airtable: contact saved tg={telegram_user_id} "
            f"platform={platform!r} platform_user_id={platform_user_id!r}"
        )
    except Exception as e:
        logger.warning(f"Airtable member_contact_collected failed: {e}")


async def member_left_group(
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    name: str | None,
    reason: str,
    left_at_iso: str,
    group_name: str | None = None,
) -> None:
    c = client()
    if not c.enabled:
        return
    where = group_name or "group"
    note = f"Left {where} at {left_at_iso}: {reason}"
    try:
        linked = _linked_whop(telegram_user_id)
        await c.append_member_note(
            telegram_user_id,
            note,
            telegram_username=telegram_username,
            name=name,
            whop_user_id=linked.get("whop_user_id"),
        )
        logger.info(f"Airtable: left group tg={telegram_user_id} reason={reason!r}")
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
        await c.record_payment(
            payment_id=payment_id,
            telegram_user_id=telegram_user_id,
            whop_user_id=whop_user_id,
            amount=amount,
            fees=fees,
            net_amount=net_amount,
            currency=currency,
            plan=plan,
            status=canonical,
            notes=notes,
        )
        logger.info(
            f"Airtable: payment {payment_id} {amount} {currency} ({canonical.value})"
        )
    except Exception as e:
        logger.warning(f"Airtable payment_recorded failed: {e}")
