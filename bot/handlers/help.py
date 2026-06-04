"""/help — list commands. Shows admin commands only to admins."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot import keyboards, texts
from bot.access import idle_after_complete_message, shows_main_menu
from bot.channel_context import ensure_private_dm, is_private_chat
from bot.community_layout import FLOW_WELCOME
from bot.decorators import is_admin, log_call


@log_call
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_private_chat(update):
        if not await ensure_private_dm(
            update, context, flow=FLOW_WELCOME, command="help"
        ):
            return

    user = update.effective_user
    if user and not shows_main_menu(user.id):
        await update.message.reply_text(
            texts.HELP_AFTER_ONBOARDING, parse_mode=ParseMode.MARKDOWN
        )
        return

    body = texts.HELP_TEXT
    if user and is_admin(user.id):
        body += texts.HELP_ADMIN_EXTRA

    await update.message.reply_text(
        body,
        reply_markup=keyboards.back_only(),
        parse_mode=ParseMode.MARKDOWN,
    )
