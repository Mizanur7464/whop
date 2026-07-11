"""
Delete non-admin messages in moderated community groups.

Main group (Fusion Strategy Community / Members):
    * Most topics are admin-only for members.
    * Members Results: members may chat; links deleted for non-admins.

Welcome group:
    * Members may chat in Members Community + Sign Up Support only.
    * Links are deleted in those two topics (anti-spam).
    * Sign Up Instructions, Results, Feedback, Welcome, Notifications: admin-only.
"""

from __future__ import annotations

import re
import time
from typing import Final

from loguru import logger
from telegram import Message, Update
from telegram.constants import MessageEntityType
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from bot.channel_context import is_main_group, is_welcome_group
from config import settings

_ADMIN_STATUSES: Final = frozenset({"creator", "administrator"})
# (chat_id, user_id) -> (allowed, monotonic expiry)
_post_cache: dict[tuple[int, int], tuple[bool, float]] = {}
_CACHE_TTL_SEC = 300.0

_LINK_HINT_RE = re.compile(
    r"https?://|www\.|t\.me/|telegram\.me/",
    re.IGNORECASE,
)


def _parse_topic_id_csv(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def _mirror_readonly_welcome_topics() -> frozenset[int]:
    """Lobby topics used as read-only chat mirrors (members may not post)."""
    ids: set[int] = set()
    if settings.telegram_chat_mirror_enabled:
        tid = (
            settings.telegram_chat_mirror_dest_topic_id
            or settings.telegram_welcome_group_topic_members_community
        )
        if tid:
            ids.add(tid)
    if settings.telegram_results_mirror_enabled:
        tid = (
            settings.telegram_results_mirror_dest_topic_id
            or settings.telegram_welcome_group_topic_results
        )
        if tid:
            ids.add(tid)
    return frozenset(ids)


def welcome_member_chat_topic_ids() -> frozenset[int]:
    """Welcome group topics where members may chat."""
    ids: set[int] = set()
    for tid in (
        settings.telegram_welcome_group_topic_members_community,
        settings.telegram_welcome_group_topic_signup_support,
    ):
        if isinstance(tid, int):
            ids.add(tid)
    ids.update(_parse_topic_id_csv(settings.group_moderation_welcome_member_chat_topics_csv))
    ids -= set(_mirror_readonly_welcome_topics())
    return frozenset(ids)


def main_member_chat_topic_ids() -> frozenset[int]:
    """Main group topics where members may chat (Members Chat + Members Results)."""
    ids: set[int] = set()
    if isinstance(settings.telegram_topic_members_chat, int):
        ids.add(settings.telegram_topic_members_chat)
    if isinstance(settings.telegram_topic_members_results, int):
        ids.add(settings.telegram_topic_members_results)
    ids.update(_parse_topic_id_csv(settings.group_moderation_member_chat_topics_csv))
    return frozenset(ids)


def welcome_admin_only_topic_ids() -> frozenset[int]:
    """Welcome group topics where member messages are deleted."""
    ids: set[int] = set()
    for tid in (
        settings.telegram_welcome_group_topic_welcome,
        settings.telegram_welcome_group_topic_notifications,
        settings.telegram_welcome_group_topic_signup_instructions,
        settings.telegram_welcome_group_topic_results,
        settings.telegram_welcome_group_topic_feedback,
    ):
        if isinstance(tid, int):
            ids.add(tid)
    return frozenset(ids)


def main_admin_only_topic_ids() -> frozenset[int]:
    """Main group topics where member messages are always deleted."""
    ids: set[int] = set()
    for tid in (
        settings.telegram_topic_signals,
        settings.telegram_topic_copytrading,
        settings.telegram_topic_support,
        settings.telegram_topic_trading_talks,
        settings.telegram_topic_education,
        settings.telegram_topic_pnl,
        settings.telegram_topic_notifications,
        settings.telegram_topic_welcome,
        settings.telegram_topic_offboard,
    ):
        if isinstance(tid, int):
            ids.add(tid)
    ids.update(_parse_topic_id_csv(settings.group_moderation_main_admin_only_topics_csv))
    return frozenset(ids)


def no_links_topic_ids() -> frozenset[int]:
    """Topics where member link posts are deleted."""
    ids = set(welcome_member_chat_topic_ids())
    ids.update(main_member_chat_topic_ids())
    ids.update(_parse_topic_id_csv(settings.group_moderation_no_links_topics_csv))
    return frozenset(ids)


def member_chat_topic_ids() -> frozenset[int]:
    """Backward-compatible alias — welcome group member-chat topics."""
    return welcome_member_chat_topic_ids()


def admin_only_topic_ids() -> frozenset[int]:
    """Backward-compatible alias — main group admin-only topics."""
    return main_admin_only_topic_ids()


def _is_welcome_member_chat_topic(msg: Message) -> bool:
    allowed = welcome_member_chat_topic_ids()
    if not allowed or not msg.message_thread_id:
        return False
    return msg.message_thread_id in allowed


def _is_main_member_chat_topic(msg: Message) -> bool:
    allowed = main_member_chat_topic_ids()
    if not allowed or not msg.message_thread_id:
        return False
    return msg.message_thread_id in allowed


def _is_main_admin_only_topic(msg: Message) -> bool:
    moderated = main_admin_only_topic_ids()
    if not moderated or not msg.message_thread_id:
        return False
    return msg.message_thread_id in moderated


def message_contains_link(msg: Message) -> bool:
    text = (msg.text or msg.caption or "").strip()
    if text and _LINK_HINT_RE.search(text):
        return True
    for ent in tuple(msg.entities or ()) + tuple(msg.caption_entities or ()):
        if ent.type in (MessageEntityType.URL, MessageEntityType.TEXT_LINK):
            return True
    return False


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

    Main group: allow Members Results; other topics admin-only.
    Welcome group: allow Members Community + Sign Up Support only.
    """
    if main_group:
        if _is_main_member_chat_topic(msg):
            return False
        return True

    if _is_welcome_member_chat_topic(msg):
        return False

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

    thread = msg.message_thread_id
    if (
        thread
        and thread in no_links_topic_ids()
        and message_contains_link(msg)
    ):
        await _delete_message(msg)
        logger.info(
            f"group_moderation: deleted link message {msg.message_id} "
            f"from user {user.id} in chat {msg.chat_id} thread {thread}"
        )
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
    # Same update path as moderation — guarantees results/chat mirror see the message
    from bot import chat_mirror, results_mirror

    await chat_mirror.try_mirror_source(update, context)
    await results_mirror.try_mirror_source(update, context)


async def on_welcome_group_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not is_welcome_group(update):
        return
    await _moderate_message(update, context, main_group=False)


def moderation_summary() -> str:
    """Human-readable summary for /topicid and logs."""
    welcome_chat = sorted(welcome_member_chat_topic_ids())
    main_chat = sorted(main_member_chat_topic_ids())
    no_links = sorted(no_links_topic_ids())
    main_blocked = sorted(main_admin_only_topic_ids())
    mirror_dest = sorted(_mirror_readonly_welcome_topics())
    lines = [
        f"Main member chat (Members Chat / Members Results): {main_chat or 'NOT SET'}",
        f"Welcome member chat: {welcome_chat or 'NOT SET'}",
        f"Lobby mirror read-only topics: {mirror_dest or 'off'}",
        (
            "Results mirror: "
            f"{settings.telegram_results_mirror_source_topic_id or settings.telegram_topic_members_results}"
            f" → "
            f"{settings.telegram_results_mirror_dest_topic_id or settings.telegram_welcome_group_topic_results}"
        ),
        f"Link ban topics: {no_links or 'member-chat topics when unset'}",
        f"Main admin-only topic IDs: {main_blocked or 'none configured'}",
    ]
    return "\n".join(lines)
