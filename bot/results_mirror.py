"""Mirror Members Results from main group → lobby Results (read-only)."""

from __future__ import annotations

from loguru import logger
from telegram import Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from bot.group_moderation import user_may_post_in_group
from bot.mirror_utils import mirror_message_to_topic
from config import settings


def results_mirror_enabled() -> bool:
    if not settings.telegram_results_mirror_enabled:
        return False
    return all(
        (
            results_source_group_id(),
            results_source_topic_id(),
            results_dest_group_id(),
            results_dest_topic_id(),
        )
    )


def results_source_group_id() -> int | None:
    return (
        settings.telegram_results_mirror_source_group_id
        or settings.telegram_main_group_id
    )


def results_source_topic_id() -> int | None:
    return (
        settings.telegram_results_mirror_source_topic_id
        or settings.telegram_topic_members_results
    )


def results_dest_group_id() -> int | None:
    return (
        settings.telegram_results_mirror_dest_group_id
        or settings.telegram_welcome_group_id
    )


def results_dest_topic_id() -> int | None:
    return (
        settings.telegram_results_mirror_dest_topic_id
        or settings.telegram_welcome_group_topic_results
    )


def results_mirror_readonly_topic_ids() -> frozenset[int]:
    dest = results_dest_topic_id()
    return frozenset({dest}) if dest and results_mirror_enabled() else frozenset()


async def on_results_source_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Copy posts from main Members Results → lobby Members Results."""
    if not results_mirror_enabled():
        return

    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or user.is_bot:
        return

    source_group = results_source_group_id()
    source_topic = results_source_topic_id()
    dest_group = results_dest_group_id()
    dest_topic = results_dest_topic_id()
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
        label="results_mirror",
    )
    if ok:
        logger.info(
            f"results_mirror: mirrored msg {msg.message_id} "
            f"{source_group}/{source_topic} → {dest_group}/{dest_topic}"
        )


async def on_results_dest_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Keep lobby Results topic read-only for members."""
    if not results_mirror_enabled():
        return

    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or user.is_bot:
        return

    dest_group = results_dest_group_id()
    dest_topic = results_dest_topic_id()
    if msg.chat_id != dest_group or msg.message_thread_id != dest_topic:
        return

    if await user_may_post_in_group(context, msg.chat_id, user.id):
        return

    try:
        await msg.delete()
    except BadRequest:
        pass
    except TelegramError as e:
        logger.warning(f"results_mirror: delete failed: {e}")
