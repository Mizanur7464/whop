"""
/claim <code> — link a Telegram user to their Whop membership.

Flow:
    1. Customer pays on Whop.
    2. Whop webhook fires `membership.went_valid`.
    3. If no Telegram ID is known yet, a 8-char claim code is generated
       and stored. The buyer should configure Whop's success page /
       email to instruct the customer to DM the bot with `/claim CODE`.
    4. Customer DMs the bot. This handler validates and grants access.
"""

from __future__ import annotations

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


CLAIM_USAGE = (
    "Usage: `/claim YOURCODE`\n\n"
    "After paying on Whop, you should have received an 8-character claim "
    "code via email or the confirmation page. Paste it here."
)

CLAIM_NOT_FOUND = (
    "We couldn't find that claim code. It may have already been used, "
    "or it might be expired.\n\n"
    "If you just paid, please wait 30 seconds and try again. "
    "Still stuck? Tap /support."
)

CLAIM_SUCCESS = (
    "✅ Your membership has been linked!\n\n"
    "Check the DM I just sent you for your group invite links."
)


@log_call
async def cmd_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_private_dm(
        update, context, flow=FLOW_WELCOME, command="claim"
    ):
        return

    user = update.effective_user

    if not context.args:
        await update.message.reply_text(
            CLAIM_USAGE, parse_mode=ParseMode.MARKDOWN
        )
        return

    code = context.args[0].strip().upper()
    claim = storage.pop_pending_claim(code)

    if not claim:
        await update.message.reply_text(
            CLAIM_NOT_FOUND,
            reply_markup=keyboards.back_only(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    whop_user_id = claim["whop_user_id"]
    product_id = claim.get("product_id")
    plan_name = plan_mapping.resolve_plan_name(product_id)
    chats = plan_mapping.resolve_chats_for_product(product_id)

    storage.link_whop_user(
        user.id,
        whop_user_id,
        whop_membership_id=claim["whop_membership_id"],
        plan=plan_name,
        status="active",
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
    )

    logger.info(
        f"Claim {code} linked tg={user.id} (@{user.username}) "
        f"-> whop={whop_user_id} membership={claim['whop_membership_id']}"
    )

    await airtable_sync.member_joined(
        telegram_user_id=user.id,
        telegram_username=user.username,
        name=" ".join(p for p in [user.first_name, user.last_name] if p) or None,
        whop_user_id=whop_user_id,
        whop_membership_id=claim["whop_membership_id"],
        plan=plan_name,
    )

    await update.message.reply_text(
        CLAIM_SUCCESS,
        parse_mode=ParseMode.MARKDOWN,
    )

    result = await telegram_ops.grant_access(user.id, chats, plan_name=plan_name)
    if not result["sent"]:
        await update.message.reply_text(
            "I couldn't DM you the invite links. Please tap /start once, "
            "then run /claim again.",
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
        lines.append(
            f"`{code}` → whop_user `{data.get('whop_user_id')}` "
            f"({data.get('plan', 'unknown')})"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
