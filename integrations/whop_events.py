"""
Whop event dispatcher.

Each handler:
    1. Extracts the membership/user from the payload
    2. Resolves the Telegram user (linked, or pending-claim path)
    3. Grants or revokes access via telegram_ops
    4. Updates local storage

Event names follow Whop's webhook docs. We accept both dotted
(`membership.went_valid`) and underscored (`membership_went_valid`)
forms so the integration is robust to docs changes.

Public entry point:
    await dispatch_event(payload)
"""

from __future__ import annotations

import secrets
from typing import Any, Callable, Awaitable

from loguru import logger

from airtable import sync as airtable_sync
from bot import storage
from config import settings
from integrations import plan_mapping, telegram_ops
from integrations.whop_copy import is_free_access, membership_received_dm

Handler = Callable[[dict], Awaitable[None]]


# ---------- Public dispatcher ----------

async def dispatch_event(payload: dict[str, Any]) -> None:
    """Route a Whop event payload to the right handler."""
    event_type = _normalize_event_name(payload.get("event") or payload.get("action") or "")
    handler = _ROUTES.get(event_type)

    if handler is None:
        logger.info(f"No handler for Whop event '{event_type}' — ignoring")
        return

    try:
        await handler(payload)
    except Exception as e:
        logger.opt(exception=e).error(f"Handler crashed for {event_type}")


def _normalize_event_name(raw: str) -> str:
    return raw.replace(".", "_").lower().strip()


# ---------- Payload helpers ----------

def _data(payload: dict) -> dict:
    """Whop usually wraps the entity under `data` (or `membership`)."""
    return (
        payload.get("data")
        or payload.get("membership")
        or payload.get("payment")
        or payload
    )


def _whop_user_id(entity: dict) -> str | None:
    user = entity.get("user") or {}
    return entity.get("user_id") or user.get("id") or entity.get("whop_user_id")


def _product_id(entity: dict) -> str | None:
    product = entity.get("product") or {}
    return entity.get("product_id") or product.get("id")


def _membership_id(entity: dict) -> str | None:
    return entity.get("id") or entity.get("membership_id")


def _payment_ref(entity: dict, payload: dict | None = None) -> str | None:
    """Whop payment / receipt id (pay_...) for success-page redirect lookup."""
    payment = entity.get("payment") if isinstance(entity.get("payment"), dict) else {}
    blocks = [entity, payment]
    if isinstance(payload, dict):
        blocks.append(payload)
        pdata = payload.get("data")
        if isinstance(pdata, dict):
            blocks.append(pdata)

    for block in blocks:
        if not isinstance(block, dict):
            continue
        for key in ("payment_id", "receipt_id", "id"):
            raw = block.get(key)
            if isinstance(raw, str) and raw.startswith("pay_"):
                return raw.strip()
    return None


def _checkout_email(entity: dict) -> str | None:
    """Email used on Whop checkout — used to auto-link via the Telegram bot."""
    user = entity.get("user") if isinstance(entity.get("user"), dict) else {}
    billing = entity.get("billing") if isinstance(entity.get("billing"), dict) else {}
    customer = entity.get("customer") if isinstance(entity.get("customer"), dict) else {}
    member = entity.get("member") if isinstance(entity.get("member"), dict) else {}

    candidates: list = [
        entity.get("email"),
        user.get("email"),
        entity.get("user_email"),
        billing.get("email"),
        customer.get("email"),
        member.get("email"),
        (user.get("billing") or {}).get("email") if isinstance(user.get("billing"), dict) else None,
    ]
    for raw in candidates:
        if isinstance(raw, str) and "@" in raw:
            return raw.strip().lower()
    return None


def _checkout_email_from_payload(payload: dict) -> str | None:
    """Try several payload layers — Whop event shape varies."""
    for block in (_data(payload), payload.get("data"), payload):
        if isinstance(block, dict):
            found = _checkout_email(block)
            if found:
                return found
    return None


def _telegram_hint(entity: dict) -> tuple[str | None, int | None]:
    """
    Try to extract Telegram identity from the Whop payload.
    Returns (username, user_id) — both optional.

    Whop can be configured to collect Telegram username at checkout
    as a custom field. We look in several common places.
    """
    user = entity.get("user") or {}
    custom = entity.get("custom_fields") or user.get("custom_fields") or {}
    metadata = entity.get("metadata") or user.get("metadata") or {}

    candidates = {**metadata, **custom}

    username = (
        candidates.get("telegram_username")
        or candidates.get("telegram")
        or user.get("telegram_username")
    )
    user_id_raw = (
        candidates.get("telegram_user_id")
        or candidates.get("telegram_id")
        or user.get("telegram_user_id")
    )
    if isinstance(username, str):
        username = username.lstrip("@").strip() or None

    user_id: int | None = None
    if user_id_raw:
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            user_id = None

    return username, user_id


# ---------- Individual handlers ----------

async def on_membership_valid(payload: dict) -> None:
    """Customer just got valid access — grant Telegram entry."""
    entity = _data(payload)
    whop_user = _whop_user_id(entity)
    membership_id = _membership_id(entity)
    product_id = _product_id(entity)

    if not whop_user or not membership_id:
        logger.warning(f"membership.went_valid missing IDs: {entity}")
        return

    plan_name = plan_mapping.resolve_plan_name(product_id)
    chats = plan_mapping.resolve_chats_for_product(product_id)

    # Path A: we already know this user's Telegram ID
    tg_id = storage.get_telegram_id_for_whop_user(whop_user)
    if tg_id is None:
        # Try the explicit hint from the webhook payload
        _, hint_id = _telegram_hint(entity)
        if hint_id:
            tg_id = hint_id
            storage.link_whop_user(tg_id, whop_user, plan=plan_name)

    if tg_id:
        local_user = storage.upsert_user(
            tg_id,
            whop_user_id=whop_user,
            whop_membership_id=membership_id,
            plan=plan_name,
            status="active",
        )
        result = await telegram_ops.grant_access(tg_id, chats, plan_name=plan_name)
        logger.info(f"Granted access to tg={tg_id} for whop={whop_user}: {result}")

        await airtable_sync.member_joined(
            telegram_user_id=tg_id,
            telegram_username=local_user.get("username"),
            name=" ".join(
                p for p in [local_user.get("first_name"), local_user.get("last_name")] if p
            ).strip() or None,
            whop_user_id=whop_user,
            whop_membership_id=membership_id,
            plan=plan_name,
        )
        return

    # Path B: no Telegram link yet — pending claim (email match or /claim code)
    code = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].upper()
    checkout_email = _checkout_email(entity) or _checkout_email_from_payload(payload)
    payment_ref = _payment_ref(entity, payload)
    storage.add_pending_claim(
        claim_code=code,
        whop_user_id=whop_user,
        whop_membership_id=membership_id,
        product_id=product_id,
        plan=plan_name,
        email=checkout_email,
        payment_id=payment_ref,
        receipt_id=payment_ref,
    )
    from integrations.whop_success_invites import ensure_pending_claim_invite_links

    claim_data = storage.find_pending_claim_by_code(code)
    if claim_data:
        _, data = claim_data
        await ensure_pending_claim_invite_links(code, data)
    if not checkout_email:
        logger.warning(
            f"Pending claim {code} has no email in webhook — "
            "user should use /whop/success or /claim CODE"
        )
    logger.info(
        f"Created pending claim {code} for whop_user={whop_user} "
        f"membership={membership_id} email={checkout_email or '—'}"
    )

    from integrations.whop_success_page import public_app_base_url

    bot_username = (settings.telegram_bot_username or "").lstrip("@")
    bot_link = f"https://t.me/{bot_username}" if bot_username else "our Telegram bot"
    base = public_app_base_url()
    if base:
        success_hint = f"{base}/whop/success"
    elif is_free_access():
        success_hint = "the activation page"
    else:
        success_hint = "the payment success page"
    dm_lines = membership_received_dm(success_hint=success_hint, bot_link=bot_link)
    if checkout_email:
        dm_lines.insert(
            2,
            f"(We have `{checkout_email}` on file — use that exact address.)",
        )

    _, hint_id = _telegram_hint(entity)
    if hint_id:
        await telegram_ops.dm(hint_id, "\n".join(dm_lines))


async def on_membership_invalid(payload: dict) -> None:
    """Subscription expired, refunded, or cancelled — revoke access."""
    entity = _data(payload)
    whop_user = _whop_user_id(entity)
    product_id = _product_id(entity)

    if not whop_user:
        logger.warning(f"membership.went_invalid missing whop_user: {entity}")
        return

    tg_id = storage.get_telegram_id_for_whop_user(whop_user)
    if tg_id is None:
        logger.info(f"membership.went_invalid for unlinked whop_user={whop_user}")
        return

    chats = plan_mapping.resolve_chats_for_product(product_id)
    if not chats:
        chats = tuple(plan_mapping.all_known_chats())

    storage.set_status(tg_id, "expired")
    result = await telegram_ops.revoke_access(
        tg_id, chats, reason="membership ended"
    )
    logger.info(f"Revoked access tg={tg_id} whop={whop_user}: {result}")
    await airtable_sync.member_status_changed(tg_id, "expired")


async def on_membership_cancel_change(payload: dict) -> None:
    """User toggled `cancel at period end`. Note it — no immediate removal."""
    entity = _data(payload)
    whop_user = _whop_user_id(entity)
    cancel_flag = entity.get("cancel_at_period_end")

    if not whop_user:
        return

    tg_id = storage.get_telegram_id_for_whop_user(whop_user)
    if tg_id is None:
        return

    storage.upsert_user(
        tg_id,
        cancel_at_period_end=bool(cancel_flag),
    )

    if cancel_flag:
        await telegram_ops.dm(
            tg_id,
            "You've scheduled cancellation at the end of the current period. "
            "You'll keep access until then. Change your mind? Reactivate from your "
            "Whop dashboard.",
        )
    else:
        await telegram_ops.dm(
            tg_id,
            "You've resumed your subscription — welcome back! Access continues.",
        )


async def on_payment_succeeded(payload: dict) -> None:
    """Mirror every successful payment into the Airtable Payments table."""
    entity = _data(payload)
    payment_id = entity.get("id") or entity.get("payment_id") or ""
    amount = entity.get("amount") or entity.get("subtotal") or 0
    currency = entity.get("currency") or "USD"
    whop_user = _whop_user_id(entity)
    product_id = _product_id(entity)
    plan_name = plan_mapping.resolve_plan_name(product_id)

    if not payment_id:
        logger.warning(f"payment_succeeded missing id: {entity}")
        return

    tg_id = storage.get_telegram_id_for_whop_user(whop_user) if whop_user else None

    await airtable_sync.payment_recorded(
        payment_id=str(payment_id),
        telegram_user_id=tg_id,
        whop_user_id=whop_user,
        amount=float(amount) / (100 if isinstance(amount, int) and amount > 1000 else 1),
        currency=str(currency),
        plan=plan_name,
        status="succeeded",
    )
    logger.info(
        f"Payment succeeded: id={payment_id} amount={amount} {currency}"
    )


async def on_payment_failed(payload: dict) -> None:
    if is_free_access():
        logger.info("payment_failed ignored — WHOP_FREE_ACCESS is enabled")
        return

    """Notify user politely so they can update card."""
    entity = _data(payload)
    whop_user = _whop_user_id(entity)
    if not whop_user:
        return
    tg_id = storage.get_telegram_id_for_whop_user(whop_user)
    if tg_id is None:
        return

    await telegram_ops.dm(
        tg_id,
        "⚠️ Your most recent payment failed. "
        "Please update your payment method in your Whop dashboard to keep access.",
    )


# ---------- Route table ----------

_ROUTES: dict[str, Handler] = {
    # Membership lifecycle (Whop V1 UI names + legacy names)
    "membership_activated": on_membership_valid,
    "membership_deactivated": on_membership_invalid,
    "membership_went_valid": on_membership_valid,
    "membership_valid": on_membership_valid,
    "membership_went_invalid": on_membership_invalid,
    "membership_invalid": on_membership_invalid,
    "membership_cancel_at_period_end_changed": on_membership_cancel_change,
    # Payments
    "payment_succeeded": on_payment_succeeded,
    "payment_failed": on_payment_failed,
}
