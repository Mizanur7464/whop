"""Mirror member chat from main group → lobby (welcome) group, read-only."""

from __future__ import annotations

from loguru import logger
from telegram import Message, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from bot.group_moderation import user_may_post_in_group
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
        or settings.telegram_topic_members_results
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
    """Lobby topics where only the bot may post (mirrored content)."""
    if not mirror_enabled():
        return frozenset()
    dest = mirror_dest_topic_id()
    return frozenset({dest}) if dest else frozenset()


def _author_label(msg: Message) -> str:
    user = msg.from_user
    if not user:
        return "Member"
    if user.full_name:
        return user.full_name
    if user.username:
        return f"@{user.username}"
    return str(user.id)


async def _mirror_text(msg: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    dest_group = mirror_dest_group_id()
    dest_topic = mirror_dest_topic_id()
    if not dest_group or not dest_topic:
        return

    author = _author_label(msg)
    body = (msg.text or msg.caption or "").strip()
    prefix = f"💬 {author}"
    text = f"{prefix}\n{body}" if body else prefix

    await context.bot.send_message(
        chat_id=dest_group,
        message_thread_id=dest_topic,
        text=text[:4096],
        disable_web_page_preview=True,
    )


async def _mirror_media(msg: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    dest_group = mirror_dest_group_id()
    dest_topic = mirror_dest_topic_id()
    if not dest_group or not dest_topic:
        return

    author = _author_label(msg)
    caption = (msg.caption or "").strip()
    cap = f"💬 {author}"
    if caption:
        cap = f"{cap}\n{caption}"

    kwargs: dict = {
        "chat_id": dest_group,
        "from_chat_id": msg.chat_id,
        "message_id": msg.message_id,
        "message_thread_id": dest_topic,
    }
    if msg.caption is not None or not caption:
        kwargs["caption"] = cap[:1024]
    await context.bot.copy_message(**kwargs)


async def on_mirror_source_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Copy allowed member chat from main group into lobby read-only topic."""
    if not mirror_enabled():
        return

    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or user.is_bot:
        return

    source_group = mirror_source_group_id()
    source_topic = mirror_source_topic_id()
    if msg.chat_id != source_group:
        return
    if msg.message_thread_id != source_topic:
        return

    if msg.text and msg.text.startswith("/"):
        return

    try:
        if msg.text:
            await _mirror_text(msg, context)
        elif msg.photo or msg.video or msg.document or msg.animation or msg.voice:
            await _mirror_media(msg, context)
        elif msg.sticker:
            await _mirror_media(msg, context)
        else:
            return
        logger.debug(
            f"chat_mirror: mirrored msg {msg.message_id} "
            f"from {source_group}/{source_topic}"
        )
    except TelegramError as e:
        logger.warning(f"chat_mirror: mirror failed for msg {msg.message_id}: {e}")


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
        logger.debug(
            f"chat_mirror: deleted member post {msg.message_id} in mirror topic"
        )
    except BadRequest:
        pass
    except TelegramError as e:
        logger.warning(f"chat_mirror: could not delete mirror-topic post: {e}")
