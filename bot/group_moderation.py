"""
Delete non-admin messages in moderated community groups.

Main group:
    * Members may chat in TELEGRAM_TOPIC_EDUCATION (+ optional extras).
    * Non-admin messages are deleted in Signals, Copy Trading, and Support.
    * Other topics stay admin-only (same as before).

Welcome group: all topics are admin-only (read + pinned Whop link).
"""

from __future__ import annotations

import time
from typing import Final

from loguru import logger
from telegram import Message, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from bot.channel_context import is_main_group, is_welcome_group
from config import settings

_ADMIN_STATUSES: Final = frozenset({"creator", "administrator"})
# (chat_id, user_id) -> (allowed, monotonic expiry)
_post_cache: dict[tuple[int, int], tuple[bool, float]] = {}
_CACHE_TTL_SEC = 300.0


def member_chat_topic_ids() -> frozenset[int]:
    """Forum topics where members may chat (Members Community)."""
    ids: set[int] = set()
    tid = settings.telegram_topic_education
    if isinstance(tid, int):
        ids.add(tid)
    extra = (settings.group_moderation_member_chat_topics_csv or "").strip()
    if extra:
        for part in extra.split(","):
            part = part.strip()
            if part.isdigit():
                ids.add(int(part))
    return frozenset(ids)


def admin_only_topic_ids() -> frozenset[int]:
    """Forum topics where member messages are always deleted (buyer request)."""
    ids: set[int] = set()
    for tid in (
        settings.telegram_topic_signals,
        settings.telegram_topic_copytrading,
        settings.telegram_topic_support,
    ):
        if isinstance(tid, int):
            ids.add(tid)
    return frozenset(ids)


def _is_member_chat_topic(msg: Message) -> bool:
    allowed = member_chat_topic_ids()
    if not allowed or not msg.message_thread_id:
        return False
    return msg.message_thread_id in allowed


def _is_admin_only_topic(msg: Message) -> bool:
    moderated = admin_only_topic_ids()
    if not moderated or not msg.message_thread_id:
        return False
    return msg.message_thread_id in moderated


def _configured_bot_admins() -> frozenset[int]:
    ids = set(settings.telegram_admin_ids)
    ids.update(settings.telegram_review_admin_ids)
    return frozenset(ids)


async def _telegram_group_admin(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int
) -> bool:
    key = (chat_id, user_id)
    now = time.monotonic()
    cached = _post_cache.get(key)
    if cached and cached[1] > now:
        return cached[0]

    allowed = False
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        allowed = member.status in _ADMIN_STATUSES
    except (BadRequest, Forbidden) as e:
        logger.debug(f"group_moderation: get_chat_member {user_id} in {chat_id}: {e}")

    _post_cache[key] = (allowed, now + _CACHE_TTL_SEC)
    return allowed


async def _delete_message(msg: Message) -> None:
    try:
        await msg.delete()
    except BadRequest:
        pass
    except Forbidden:
        logger.warning(
            "group_moderation: cannot delete messages — make the bot a group admin "
            "with 'Delete messages' permission"
        )


async def user_may_post_in_group(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int
) -> bool:
    if user_id in _configured_bot_admins():
        return True
    return await _telegram_group_admin(context, chat_id, user_id)


def should_delete_member_message(msg: Message, *, main_group: bool) -> bool:
    """
    Return True when a non-admin member message should be deleted.

    Welcome group: always delete member messages.
    Main group: allow Members Community; delete signals/copy/support + other topics.
    """
    if not main_group:
        return True

    if _is_member_chat_topic(msg):
        return False

    if _is_admin_only_topic(msg):
        return True

    # General lane + other admin-only topics (PnL, notifications, etc.)
    return True


async def _moderate_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    main_group: bool,
) -> None:
    if not settings.group_moderation_enabled:
        return

    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or user.is_bot:
        return

    if await user_may_post_in_group(context, msg.chat_id, user.id):
        return

    if not should_delete_member_message(msg, main_group=main_group):
        return

    await _delete_message(msg)
    logger.info(
        f"group_moderation: deleted message {msg.message_id} "
        f"from user {user.id} in chat {msg.chat_id} "
        f"thread {msg.message_thread_id}"
    )


async def on_main_group_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not is_main_group(update):
        return
    await _moderate_message(update, context, main_group=True)


async def on_welcome_group_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not is_welcome_group(update):
        return
    await _moderate_message(update, context, main_group=False)


def moderation_summary() -> str:
    """Human-readable summary for /topicid and logs."""
    allowed = sorted(member_chat_topic_ids())
    blocked = sorted(admin_only_topic_ids())
    lines = [
        f"Members chat allowed: {allowed or 'NOT SET — set TELEGRAM_TOPIC_EDUCATION'}",
        f"Admin-only (delete member msgs): {blocked or 'none configured'}",
    ]
    return "\n".join(lines)
