"""
/claim <code> — link a Telegram user to their Whop membership.

After Whop payment (no Telegram on file yet):
    1. Webhook stores a pending claim keyed by checkout email.
    2. Customer sends /claim in the bot, then replies with checkout email.
    3. Bot redeems automatically and DMs group invite links.

/claim CODE still works as a fallback.
"""

from __future__ import annotations

import re

from loguru import logger
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from airtable import sync as airtable_sync
from bot import jobs, keyboards, storage
from bot.channel_context import ensure_private_dm
from bot.community_layout import FLOW_WELCOME
from bot.decorators import is_admin, log_call
from bot.main_group_access import refresh_commands_for_user
from integrations import plan_mapping, telegram_ops
from integrations.whop_claim_resolve import fetch_membership_by_email, new_claim_code
from integrations.whop_copy import (
    claim_already_linked,
    claim_code_not_found,
    claim_email_not_found,
    claim_email_prompt,
    claim_success_message,
)

USER_DATA_AWAITING_WHOP_EMAIL = "awaiting_whop_email"


def _email_pattern(text: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text.strip()))


def whop_email_activation_active(_: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.user_data.get(USER_DATA_AWAITING_WHOP_EMAIL))


async def reply_if_already_linked(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_user_id: int,
) -> bool:
    """If user already claimed, warn and return True (caller should stop)."""
    if is_admin(telegram_user_id):
        return False
    if not storage.has_whop_link(telegram_user_id):
        return False
    if not update.message:
        return True
    context.user_data.pop(USER_DATA_AWAITING_WHOP_EMAIL, None)
    logger.info(f"claim: already linked tg={telegram_user_id}")
    await update.message.reply_text(
        claim_already_linked(),
        reply_markup=keyboards.back_only(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return True


def begin_whop_email_activation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    context.user_data[USER_DATA_AWAITING_WHOP_EMAIL] = True


async def prompt_whop_activation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message or not update.effective_user:
        return
    if await reply_if_already_linked(update, context, update.effective_user.id):
        return
    begin_whop_email_activation(update, context)
    await update.message.reply_text(
        claim_email_prompt(), parse_mode=ParseMode.MARKDOWN
    )


async def fulfill_claim(
    *,
    telegram_user_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    code: str,
    claim: dict,
) -> dict:
    """Link Whop membership and grant Telegram group access."""
    whop_user_id = claim["whop_user_id"]
    product_id = claim.get("product_id")
    plan_name = plan_mapping.resolve_plan_name(product_id)
    chats = plan_mapping.resolve_chats_for_product(product_id)

    storage.link_whop_user(
        telegram_user_id,
        whop_user_id,
        whop_membership_id=claim["whop_membership_id"],
        plan=plan_name,
        status="active",
        username=username or "",
        first_name=first_name or "",
        last_name=last_name or "",
    )

    logger.info(
        f"Claim {code} linked tg={telegram_user_id} (@{username}) "
        f"-> whop={whop_user_id} membership={claim['whop_membership_id']}"
    )

    result = await telegram_ops.grant_access(
        telegram_user_id, chats, plan_name=plan_name
    )
    try:
        await airtable_sync.member_joined(
            telegram_user_id=telegram_user_id,
            telegram_username=username,
            name=" ".join(p for p in [first_name, last_name] if p) or None,
            whop_user_id=whop_user_id,
            whop_membership_id=claim["whop_membership_id"],
            plan=plan_name,
        )
    except Exception as e:
        logger.warning(f"fulfill_claim: Airtable sync failed for tg={telegram_user_id}: {e}")
    try:
        await refresh_commands_for_user(
            telegram_ops.bot(), telegram_user_id
        )
    except Exception as e:
        logger.warning(f"fulfill_claim: refresh commands failed for tg={telegram_user_id}: {e}")
    return {"plan_name": plan_name, "grant": result}


@log_call
async def cmd_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_private_dm(
        update, context, flow=FLOW_WELCOME, command="claim"
    ):
        return

    user = update.effective_user
    if await reply_if_already_linked(update, context, user.id):
        return

    if not context.args:
        await prompt_whop_activation(update, context)
        return

    context.user_data.pop(USER_DATA_AWAITING_WHOP_EMAIL, None)
    code = context.args[0].strip().upper()
    claim = storage.pop_pending_claim(code)

    if not claim:
        await update.message.reply_text(
            claim_code_not_found(),
            reply_markup=keyboards.back_only(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(
        claim_success_message(), parse_mode=ParseMode.MARKDOWN
    )

    outcome = await fulfill_claim(
        telegram_user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        code=code,
        claim=claim,
    )
    if not outcome["grant"]["sent"]:
        await update.message.reply_text(
            "I couldn't DM you the invite links. Please tap /start once, "
            "then send `/claim` again or `/claim` with your code.",
            parse_mode=ParseMode.MARKDOWN,
        )

    jobs.schedule_onboarding_reminder(context.application, user.id)


@log_call
async def on_whop_email_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Redeem pending Whop payment by matching checkout email."""
    if not update.message or not update.effective_user:
        return

    user = update.effective_user
    if await reply_if_already_linked(update, context, user.id):
        return

    text = (update.message.text or "").strip()
    if not _email_pattern(text):
        await update.message.reply_text(
            "Please send a valid email address (the one you used on Whop).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    logger.info(
        f"claim/email: tg={user.id} @{user.username} submitted email={text!r} | "
        f"{storage.pending_claims_debug_summary()}"
    )

    found = storage.find_pending_claim_by_email(text)
    if found:
        code, claim = found
        claim = storage.pop_pending_claim(code)
        if not claim:
            logger.error(f"claim/email: pop_pending_claim failed for code={code}")
            await update.message.reply_text(
                claim_email_not_found(), parse_mode=ParseMode.MARKDOWN
            )
            return
        logger.info(f"claim/email: redeemed local pending code={code}")
    else:
        logger.warning("claim/email: no local pending — trying Whop API fallback")
        resolved = await fetch_membership_by_email(text)
        if not resolved or not resolved.get("whop_user_id"):
            logger.error(f"claim/email: Whop API also found nothing for {text!r}")
            await update.message.reply_text(
                claim_email_not_found(),
                reply_markup=keyboards.back_only(),
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        code = new_claim_code()
        claim = resolved
        logger.info(
            f"claim/email: Whop API resolved membership={claim.get('whop_membership_id')} "
            f"synthetic_code={code}"
        )

    context.user_data.pop(USER_DATA_AWAITING_WHOP_EMAIL, None)
    await update.message.reply_text(
        claim_success_message(), parse_mode=ParseMode.MARKDOWN
    )

    outcome = await fulfill_claim(
        telegram_user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        code=code,
        claim=claim,
    )
    if not outcome["grant"]["sent"]:
        logger.error(
            f"claim/email: grant_access failed for tg={user.id} links={outcome['grant'].get('links')}"
        )
        await update.message.reply_text(
            "Membership linked, but invite links failed. Tap /start and contact /support.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        logger.success(f"claim/email: invite sent to tg={user.id} plan={outcome.get('plan_name')}")

    jobs.schedule_onboarding_reminder(context.application, user.id)


# ---------- Admin: /claims (list pending) ----------

@log_call
async def cmd_pending_claims(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only: list pending claims so support can help users manually."""
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    items = list(storage._pending_claims.items())  # noqa: SLF001 - admin debug
    if not items:
        await update.message.reply_text("No pending claims.")
        return

    lines = ["*Pending Claims*", ""]
    for code, data in items[-20:]:
        email = data.get("email") or "—"
        lines.append(
            f"`{code}` → whop_user `{data.get('whop_user_id')}` "
            f"email `{email}` ({data.get('plan', 'unknown')})"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
