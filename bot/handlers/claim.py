"""
/claim <code> — link a Telegram user to their Whop membership.

After Whop payment (no Telegram on file yet):
    1. Webhook stores a pending claim keyed by checkout email.
    2. Customer sends /claim in the bot, then replies with checkout email.
    3. Bot redeems automatically and DMs group invite links.

/claim CODE still works as a fallback.
"""

from __future__ import annotations

import asyncio
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
from config import settings
from integrations import plan_mapping, telegram_ops
from integrations.whop_claim_resolve import fetch_membership_by_email, new_claim_code
from integrations.whop_copy import (
    claim_already_linked,
    claim_code_not_found,
    claim_email_not_found,
    claim_email_prompt,
    claim_invite_failed_message,
    claim_invite_message,
    claim_processing_message,
    claim_success_message,
)

USER_DATA_AWAITING_WHOP_EMAIL = "awaiting_whop_email"
_claim_email_busy: set[int] = set()


class WhopLookupTimeout(Exception):
    """Whop API email lookup exceeded time limit."""


def looks_like_claim_email(text: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text.strip()))


def whop_email_activation_active(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    if context.user_data.get(USER_DATA_AWAITING_WHOP_EMAIL):
        return True
    user = update.effective_user
    return bool(user and storage.is_awaiting_claim_email(user.id))


def should_handle_whop_email_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Route private text to claim/email flow (memory flag or unlinked user email)."""
    if not update.message or not update.effective_user:
        return False
    if whop_email_activation_active(update, context):
        return True
    user = update.effective_user
    if is_admin(user.id) or storage.has_whop_link(user.id):
        return False
    return looks_like_claim_email((update.message.text or "").strip())


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
    storage.clear_awaiting_claim_email(telegram_user_id)
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
    user = update.effective_user
    if user:
        storage.set_awaiting_claim_email(user.id, True)


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
    bot=None,
) -> dict:
    """Link Whop membership and grant Telegram group access."""
    whop_user_id = claim["whop_user_id"]
    product_id = claim.get("product_id")
    plan_name = plan_mapping.resolve_plan_name(product_id)
    chats = plan_mapping.resolve_chats_for_product(product_id)

    storage.clear_awaiting_claim_email(telegram_user_id)
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

    invite_url: str | None = None
    try:
        invite_url = await asyncio.wait_for(
            telegram_ops.create_main_group_invite(
                name=f"claim-{code}-{telegram_user_id}"
            ),
            timeout=12.0,
        )
    except asyncio.TimeoutError:
        logger.error(
            f"fulfill_claim: invite link timed out for tg={telegram_user_id}"
        )
    if not invite_url and chats:
        logger.warning(
            f"fulfill_claim: main invite failed, trying plan chats for tg={telegram_user_id}"
        )
        try:
            links = await asyncio.wait_for(
                telegram_ops.build_invite_link_list(chats, plan_name=plan_name),
                timeout=12.0,
            )
            if links:
                invite_url = links[0].get("url")
        except asyncio.TimeoutError:
            logger.error(f"fulfill_claim: fallback invite timed out tg={telegram_user_id}")

    result = {
        "sent": bool(invite_url),
        "links": {settings.telegram_main_group_id: invite_url}
        if settings.telegram_main_group_id
        else {},
        "invite_url": invite_url,
    }

    async def _deferred_sync() -> None:
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
            logger.warning(
                f"fulfill_claim: Airtable sync failed for tg={telegram_user_id}: {e}"
            )
        if bot is not None:
            try:
                await refresh_commands_for_user(bot, telegram_user_id)
            except Exception as e:
                logger.warning(
                    f"fulfill_claim: refresh commands failed for tg={telegram_user_id}: {e}"
                )

    asyncio.create_task(_deferred_sync())
    return {"plan_name": plan_name, "grant": result, "invite_url": invite_url}


async def _send_claim_outcome_to_chat(
    bot,
    chat_id: int,
    *,
    telegram_user_id: int,
    outcome: dict,
) -> None:
    """Post success + invite link in the user's private chat."""
    try:
        await bot.send_message(
            chat_id,
            claim_success_message(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        await bot.send_message(
            chat_id, claim_success_message(), parse_mode=None
        )
    invite_url = outcome.get("invite_url") or outcome.get("grant", {}).get("invite_url")
    if invite_url:
        await bot.send_message(
            chat_id,
            claim_invite_message(invite_url),
            parse_mode=None,
            disable_web_page_preview=False,
        )
        logger.success(f"claim: invite link sent in-chat for tg={telegram_user_id}")
    else:
        logger.error(
            f"claim: no invite URL for tg={telegram_user_id} "
            f"main_group={settings.telegram_main_group_id}"
        )
        try:
            await bot.send_message(
                chat_id,
                claim_invite_failed_message(),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            await bot.send_message(
                chat_id, claim_invite_failed_message(), parse_mode=None
            )


async def _send_claim_outcome_messages(
    update: Update, outcome: dict
) -> None:
    """Post success + invite link in the same private chat (not a separate DM)."""
    if not update.message or not update.effective_user:
        return
    await _send_claim_outcome_to_chat(
        update.get_bot(),
        update.effective_chat.id,
        telegram_user_id=update.effective_user.id,
        outcome=outcome,
    )


async def _resolve_claim_from_email(text: str) -> tuple[str, dict] | None:
    """Find pending claim locally or via Whop API."""
    found = storage.find_pending_claim_by_email(text)
    if found:
        code, claim = found
        claim = storage.pop_pending_claim(code)
        if not claim:
            logger.error(f"claim/email: pop_pending_claim failed for code={code}")
            return None
        logger.info(f"claim/email: redeemed local pending code={code}")
        return code, claim

    logger.warning("claim/email: no local pending — trying Whop API fallback")
    try:
        resolved = await asyncio.wait_for(
            fetch_membership_by_email(text),
            timeout=18.0,
        )
    except asyncio.TimeoutError:
        logger.error(f"claim/email: Whop API lookup timed out for {text!r}")
        raise WhopLookupTimeout from None

    if not resolved or not resolved.get("whop_user_id"):
        logger.error(f"claim/email: Whop API also found nothing for {text!r}")
        return None

    code = new_claim_code()
    logger.info(
        f"claim/email: Whop API resolved membership={resolved.get('whop_membership_id')} "
        f"synthetic_code={code}"
    )
    return code, resolved


async def _complete_email_claim(
    *,
    application,
    chat_id: int,
    user_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    email: str,
) -> None:
    bot = application.bot
    try:
        resolved = await _resolve_claim_from_email(email)
        if not resolved:
            await bot.send_message(
                chat_id,
                claim_email_not_found(),
                reply_markup=keyboards.back_only(),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        code, claim = resolved
        storage.clear_awaiting_claim_email(user_id)

        outcome = await asyncio.wait_for(
            fulfill_claim(
                telegram_user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                code=code,
                claim=claim,
                bot=bot,
            ),
            timeout=30.0,
        )
        await _send_claim_outcome_to_chat(
            bot, chat_id, telegram_user_id=user_id, outcome=outcome
        )
        jobs.schedule_onboarding_reminder(application, user_id)
    except WhopLookupTimeout:
        await bot.send_message(
            chat_id,
            "Whop lookup timed out. Please try again in 30 seconds.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except asyncio.TimeoutError:
        logger.error(f"claim/email: fulfill timed out for tg={user_id}")
        try:
            await bot.send_message(
                chat_id,
                claim_invite_failed_message(),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
    except Exception as e:
        logger.exception(f"claim/email: background claim failed for tg={user_id}: {e}")
        try:
            await bot.send_message(
                chat_id,
                "Something went wrong linking your account. Please send `/claim` and try again.",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
    finally:
        _claim_email_busy.discard(user_id)


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
    storage.clear_awaiting_claim_email(user.id)
    code = context.args[0].strip().upper()
    claim = storage.pop_pending_claim(code)

    if not claim:
        await update.message.reply_text(
            claim_code_not_found(),
            reply_markup=keyboards.back_only(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    outcome = await fulfill_claim(
        telegram_user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        code=code,
        claim=claim,
        bot=context.bot,
    )
    await _send_claim_outcome_messages(update, outcome)

    jobs.schedule_onboarding_reminder(context.application, user.id)


@log_call
async def on_whop_email_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Redeem pending Whop payment by matching checkout email."""
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    user = update.effective_user
    chat = update.effective_chat

    if await reply_if_already_linked(update, context, user.id):
        return

    text = (update.message.text or "").strip()
    if not looks_like_claim_email(text):
        await update.message.reply_text(
            "Please send a valid email address (the one you used on Whop).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if user.id in _claim_email_busy:
        await update.message.reply_text(
            claim_processing_message(),
            parse_mode=None,
        )
        return

    _claim_email_busy.add(user.id)
    context.user_data.pop(USER_DATA_AWAITING_WHOP_EMAIL, None)

    await update.message.reply_text(
        claim_processing_message(),
        parse_mode=None,
    )

    logger.info(
        f"claim/email: tg={user.id} @{user.username} submitted email={text!r} | "
        f"{storage.pending_claims_debug_summary()}"
    )

    asyncio.create_task(
        _complete_email_claim(
            application=context.application,
            chat_id=chat.id,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            email=text,
        )
    )


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
