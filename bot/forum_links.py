"""Forum topic deep links (t.me/.../topic_id) for member onboarding."""

from __future__ import annotations

from loguru import logger
from telegram import Bot
from telegram.error import TelegramError

from config import settings


def entry_topic_id() -> int | None:
    """Topic new members should open first (default: Signals)."""
    if settings.telegram_entry_topic_id is not None:
        return settings.telegram_entry_topic_id
    return settings.telegram_topic_signals


def build_topic_deep_link(
    chat_id: int, topic_id: int, *, username: str | None = None
) -> str:
    """Build a t.me link that opens a forum topic ([core.telegram.org/api/links](https://core.telegram.org/api/links))."""
    if username:
        return f"https://t.me/{username.lstrip('@')}/{topic_id}"
    cid = str(chat_id)
    if cid.startswith("-100"):
        internal = cid[4:]
    else:
        internal = cid.lstrip("-")
    return f"https://t.me/c/{internal}/{topic_id}"


async def chat_username(bot: Bot, chat_id: int) -> str | None:
    try:
        chat = await bot.get_chat(chat_id)
        return chat.username
    except TelegramError as e:
        logger.debug(f"forum_links: get_chat({chat_id}) failed: {e}")
        return None


async def entry_topic_deep_link(
    bot: Bot, *, chat_id: int | None = None
) -> str | None:
    gid = chat_id or settings.telegram_main_group_id
    topic_id = entry_topic_id()
    if not gid or not topic_id:
        return None
    username = await chat_username(bot, gid)
    return build_topic_deep_link(gid, topic_id, username=username)
