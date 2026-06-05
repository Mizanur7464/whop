"""Block member commands in private DM until they join the main group."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.channel_context import _command_name, is_private_chat
from bot.decorators import is_admin
from bot.main_group_access import needs_claim_only_menu, refresh_commands_for_user
from integrations.whop_copy import claim_only_command_hint

# onboarding runs its own main-group check and always replies
_ALLOWED_BEFORE_MAIN = frozenset({"claim", "start", "onboarding", "welcome"})


async def block_until_main_group(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Return True when the command was blocked (caller should stop).

    Only /claim and /start work until the user is in TELEGRAM_MAIN_GROUP_ID.
    """
    if not is_private_chat(update) or not update.effective_user or not update.message:
        return False

    user = update.effective_user
    if is_admin(user.id):
        return False

    name = _command_name(update)
    if not name or name in _ALLOWED_BEFORE_MAIN:
        return False

    if not await needs_claim_only_menu(context.bot, user.id):
        return False

    try:
        await refresh_commands_for_user(context.bot, user.id)
        await update.message.reply_text(
            claim_only_command_hint(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        from loguru import logger

        logger.warning(f"command_gate: could not reply to {user.id}: {e}")
        try:
            await update.message.reply_text(
                claim_only_command_hint().replace("*", ""),
                parse_mode=None,
            )
        except Exception:
            pass
    return True
