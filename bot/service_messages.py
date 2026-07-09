"""Auto-delete join/leave service messages in community groups."""

from __future__ import annotations

from loguru import logger
from telegram import Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from config import settings


def _monitored_chat_ids() -> frozenset[int]:
    ids: set[int] = set()
    if settings.telegram_main_group_id:
        ids.add(settings.telegram_main_group_id)
    if settings.telegram_welcome_group_id:
        ids.add(settings.telegram_welcome_group_id)
    return frozenset(ids)


async def on_service_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Delete 'X joined/left the group' lines when the bot can."""
    if not settings.telegram_service_message_cleanup:
        return

    msg = update.effective_message
    if not msg or msg.chat_id not in _monitored_chat_ids():
        return

    if not (msg.left_chat_member or msg.new_chat_members):
        return

    try:
        await msg.delete()
        logger.debug(
            f"service_messages: deleted service message {msg.message_id} "
            f"in chat {msg.chat_id}"
        )
    except BadRequest:
        pass
    except Forbidden:
        logger.warning(
            "service_messages: cannot delete — bot needs admin + Delete messages"
        )
