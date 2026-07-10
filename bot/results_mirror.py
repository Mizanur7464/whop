"""Mirror admin results from main Members Results → lobby Results (read-only)."""

from __future__ import annotations

from loguru import logger
from telegram import Message, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from bot.group_moderation import user_may_post_in_group
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


async def _mirror_results_text(msg: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    dest_group = results_dest_group_id()
    dest_topic = results_dest_topic_id()
    if not dest_group or not dest_topic:
        return
    body = (msg.text or "").strip()
    if not body:
        return
    await context.bot.send_message(
        chat_id=dest_group,
        message_thread_id=dest_topic,
        text=body[:4096],
        disable_web_page_preview=True,
    )


async def _mirror_results_media(msg: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    dest_group = results_dest_group_id()
    dest_topic = results_dest_topic_id()
    if not dest_group or not dest_topic:
        return
    kwargs: dict = {
        "chat_id": dest_group,
        "from_chat_id": msg.chat_id,
        "message_id": msg.message_id,
        "message_thread_id": dest_topic,
    }
    if msg.caption:
        kwargs["caption"] = msg.caption[:1024]
    await context.bot.copy_message(**kwargs)


async def on_results_source_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Copy admin/broadcast posts from main Members Results → lobby Results."""
    if not results_mirror_enabled():
        return

    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or user.is_bot:
        return

    if msg.chat_id != results_source_group_id():
        return
    if msg.message_thread_id != results_source_topic_id():
        return

    if msg.text and msg.text.startswith("/"):
        return

    try:
        if msg.text:
            await _mirror_results_text(msg, context)
        elif msg.photo or msg.video or msg.document or msg.animation or msg.voice:
            await _mirror_results_media(msg, context)
        else:
            return
        logger.debug(
            f"results_mirror: mirrored msg {msg.message_id} "
            f"→ lobby topic {results_dest_topic_id()}"
        )
    except TelegramError as e:
        logger.warning(f"results_mirror: failed msg {msg.message_id}: {e}")


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
