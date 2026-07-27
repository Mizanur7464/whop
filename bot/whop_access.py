"""Block bot flows until the user has linked a Whop membership via /claim."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot import storage
from bot.decorators import is_admin
from bot.handlers import claim
from integrations.whop_copy import claim_email_prompt


async def block_without_whop_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """
    Return True when the update was blocked (no Whop link).

    Admins are always allowed through.
    """
    user = update.effective_user
    if not user or is_admin(user.id):
        return False
    if storage.has_whop_link(user.id):
        return False

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            claim_email_prompt(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return True

    if update.message:
        await claim.prompt_whop_activation(update, context)
        return True

    return True
