"""Shared helpers for forum topic message mirroring."""

from __future__ import annotations

from loguru import logger
from telegram import Message
from telegram.error import TelegramError
from telegram.ext import ContextTypes


def author_label(msg: Message) -> str:
    user = msg.from_user
    if not user:
        return "Member"
    if user.full_name:
        return user.full_name
    if user.username:
        return f"@{user.username}"
    return str(user.id)


def _has_mirrorable_media(msg: Message) -> bool:
    return bool(
        msg.photo
        or msg.video
        or msg.document
        or msg.animation
        or msg.voice
        or msg.sticker
        or msg.video_note
        or msg.audio
    )


async def mirror_message_to_topic(
    msg: Message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    dest_group_id: int,
    dest_topic_id: int,
    label: str,
) -> bool:
    """Copy any forum message into a destination topic (text, media, forwards)."""
    author = author_label(msg)
    body = (msg.text or msg.caption or "").strip()
    prefix = f"💬 {author}"
    text = f"{prefix}\n{body}" if body else prefix

    try:
        if msg.text and not _has_mirrorable_media(msg):
            await context.bot.send_message(
                chat_id=dest_group_id,
                message_thread_id=dest_topic_id,
                text=text[:4096],
                disable_web_page_preview=True,
            )
            return True

        if _has_mirrorable_media(msg) or msg.forward_origin or msg.forward_date:
            kwargs: dict = {
                "chat_id": dest_group_id,
                "from_chat_id": msg.chat_id,
                "message_id": msg.message_id,
                "message_thread_id": dest_topic_id,
            }
            if body:
                kwargs["caption"] = text[:1024]
            await context.bot.copy_message(**kwargs)
            return True

        if body:
            await context.bot.send_message(
                chat_id=dest_group_id,
                message_thread_id=dest_topic_id,
                text=text[:4096],
                disable_web_page_preview=True,
            )
            return True
    except TelegramError as e:
        logger.warning(f"{label}: mirror failed msg={msg.message_id}: {e}")

    return False
