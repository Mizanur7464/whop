"""/start — entry point. Routes new users into onboarding (private DM only)."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot import jobs, keyboards, storage, texts
from bot.access import idle_after_complete_message, shows_main_menu
from bot.channel_context import ensure_welcome_context
from bot.decorators import is_admin, log_call
from bot.main_group_access import needs_claim_only_menu, refresh_commands_for_user
from bot.handlers import claim, copy_trading, onboarding, support_channel


@log_call
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_welcome_context(update, context):
        return

    user = update.effective_user
    chat = update.effective_chat

    if chat and chat.type == "private":
        try:
            await refresh_commands_for_user(
                context.bot, user.id, is_admin_user=is_admin(user.id)
            )
        except Exception:
            pass

    storage.upsert_user(
        user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        language_code=user.language_code or "",
    )

    payload = (context.args[0].lower() if context.args else "").strip()

    if chat and chat.type == "private" and await needs_claim_only_menu(
        context.bot, user.id
    ):
        if payload in ("copytrading", "copy_trading", "support", "supportform"):
            return
        if payload in ("paid", "whop", "activate", "claim") or not payload:
            await claim.prompt_whop_activation(update, context)
            return

    if payload in ("paid", "whop", "activate", "claim"):
        if chat and chat.type == "private":
            await claim.prompt_whop_activation(update, context)
        return

    if payload in ("copytrading", "copy_trading"):
        await copy_trading.cmd_copytrading(update, context)
        return
    if payload in ("support", "supportform"):
        await support_channel.cmd_support(update, context)
        return

    if onboarding.needs_onboarding(user.id):
        await onboarding.show_welcome(update, context)
        jobs.schedule_onboarding_reminder(context.application, user.id)
        return

    if not shows_main_menu(user.id):
        await update.message.reply_text(idle_after_complete_message())
        return

    await update.message.reply_text(
        texts.WELCOME_RETURNING.format(first_name=user.first_name or "there"),
        reply_markup=keyboards.main_menu(is_admin=is_admin(user.id)),
        parse_mode=ParseMode.MARKDOWN,
    )
