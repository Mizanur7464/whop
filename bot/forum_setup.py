"""Startup forum setup: hide General topic in forum supergroups."""

from __future__ import annotations

from loguru import logger
from telegram import Bot
from telegram.error import TelegramError

from config import settings


async def hide_general_topic(bot: Bot, chat_id: int) -> bool:
    try:
        ok = await bot.hide_general_forum_topic(chat_id=chat_id)
        if ok:
            logger.info(f"forum_setup: hid General topic in chat {chat_id}")
        return bool(ok)
    except TelegramError as e:
        logger.warning(
            f"forum_setup: hide_general_forum_topic failed for {chat_id}: {e}"
        )
        return False


async def apply_forum_setup(bot: Bot) -> None:
    """Hide General/All in configured forum groups (requires can_manage_topics)."""
    if not settings.telegram_forum_hide_general:
        return
    for gid in (settings.telegram_main_group_id, settings.telegram_welcome_group_id):
        if gid:
            await hide_general_topic(bot, gid)
