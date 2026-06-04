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
from integrations import plan_mapping, telegram_ops
from integrations.whop_copy import (
    claim_code_not_found,
    claim_email_not_found,
    claim_email_prompt,
)

USER_DATA_AWAITING_WHOP_EMAIL = "awaiting_whop_email"

CLAIM_SUCCESS = (
    "Your membership is linked.\n\n"
    "Check this chat for your group invite link(s). "
    "Then send /onboarding to complete setup."
)


def _email_pattern(text: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text.strip()))


def whop_email_activation_active(_: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.user_data.get(USER_DATA_AWAITING_WHOP_EMAIL))


def begin_whop_email_activation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    context.user_data[USER_DATA_AWAITING_WHOP_EMAIL] = True


async def prompt_whop_activation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message:
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

    await airtable_sync.member_joined(
        telegram_user_id=telegram_user_id,
        telegram_username=username,
        name=" ".join(p for p in [first_name, last_name] if p) or None,
        whop_user_id=whop_user_id,
        whop_membership_id=claim["whop_membership_id"],
        plan=plan_name,
    )

    result = await telegram_ops.grant_access(
        telegram_user_id, chats, plan_name=plan_name
    )
    return {"plan_name": plan_name, "grant": result}


@log_call
async def cmd_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_private_dm(
        update, context, flow=FLOW_WELCOME, command="claim"
    ):
        return

    user = update.effective_user

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

    await update.message.reply_text(CLAIM_SUCCESS, parse_mode=ParseMode.MARKDOWN)

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

    text = (update.message.text or "").strip()
    if not _email_pattern(text):
        await update.message.reply_text(
            "Please send a valid email address (the one you used on Whop).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    user = update.effective_user
    found = storage.find_pending_claim_by_email(text)
    if not found:
        await update.message.reply_text(
            claim_email_not_found(),
            reply_markup=keyboards.back_only(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    code, claim = found
    claim = storage.pop_pending_claim(code)
    if not claim:
        await update.message.reply_text(
            claim_email_not_found(), parse_mode=ParseMode.MARKDOWN
        )
        return

    context.user_data.pop(USER_DATA_AWAITING_WHOP_EMAIL, None)
    await update.message.reply_text(CLAIM_SUCCESS, parse_mode=ParseMode.MARKDOWN)

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
            "Membership linked, but invite links failed. Tap /start and contact /support.",
            parse_mode=ParseMode.MARKDOWN,
        )

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
