"""Mirror member chat from main group → lobby (welcome) group, read-only."""

from __future__ import annotations

from loguru import logger
from telegram import Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from bot.group_moderation import user_may_post_in_group
from bot.mirror_utils import mirror_message_to_topic
from config import settings


def mirror_enabled() -> bool:
    if not settings.telegram_chat_mirror_enabled:
        return False
    return all(
        (
            mirror_source_group_id(),
            mirror_source_topic_id(),
            mirror_dest_group_id(),
            mirror_dest_topic_id(),
        )
    )


def mirror_source_group_id() -> int | None:
    return (
        settings.telegram_chat_mirror_source_group_id
        or settings.telegram_main_group_id
    )


def mirror_source_topic_id() -> int | None:
    return (
        settings.telegram_chat_mirror_source_topic_id
        or settings.telegram_topic_members_chat
    )


def mirror_dest_group_id() -> int | None:
    return (
        settings.telegram_chat_mirror_dest_group_id
        or settings.telegram_welcome_group_id
    )


def mirror_dest_topic_id() -> int | None:
    return (
        settings.telegram_chat_mirror_dest_topic_id
        or settings.telegram_welcome_group_topic_members_community
    )


def mirror_readonly_topic_ids() -> frozenset[int]:
    if not mirror_enabled():
        return frozenset()
    dest = mirror_dest_topic_id()
    return frozenset({dest}) if dest else frozenset()


async def on_mirror_source_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Copy posts from main Members Chat → lobby Members chat."""
    if not mirror_enabled():
        return

    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or user.is_bot:
        return

    source_group = mirror_source_group_id()
    source_topic = mirror_source_topic_id()
    dest_group = mirror_dest_group_id()
    dest_topic = mirror_dest_topic_id()
    if not source_group or not source_topic or not dest_group or not dest_topic:
        return

    if msg.chat_id != source_group or msg.message_thread_id != source_topic:
        return

    if msg.text and msg.text.startswith("/"):
        return

    ok = await mirror_message_to_topic(
        msg,
        context,
        dest_group_id=dest_group,
        dest_topic_id=dest_topic,
        label="chat_mirror",
    )
    if ok:
        logger.info(
            f"chat_mirror: mirrored msg {msg.message_id} "
            f"{source_group}/{source_topic} → {dest_group}/{dest_topic}"
        )


async def on_mirror_dest_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Keep lobby mirror topic read-only — delete member posts."""
    if not mirror_enabled():
        return

    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or user.is_bot:
        return

    dest_group = mirror_dest_group_id()
    dest_topic = mirror_dest_topic_id()
    if msg.chat_id != dest_group or msg.message_thread_id != dest_topic:
        return

    if await user_may_post_in_group(context, msg.chat_id, user.id):
        return

    try:
        await msg.delete()
    except BadRequest:
        pass
    except TelegramError as e:
        logger.warning(f"chat_mirror: could not delete mirror-topic post: {e}")
