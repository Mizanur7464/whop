"""Thread-aware Telegram sends for forum (topics) groups."""

from __future__ import annotations

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.community_layout import message_thread_kwargs


def chat_id(update: Update) -> int:
    return update.effective_chat.id


async def send_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    markup: InlineKeyboardMarkup | None = None,
    flow: str | None = None,
    parse_mode: str = ParseMode.MARKDOWN,
    disable_preview: bool = True,
) -> None:
    if not update.effective_chat:
        return
    kwargs = message_thread_kwargs(update, flow)
    try:
        await context.bot.send_message(
            chat_id=chat_id(update),
            text=text,
            reply_markup=markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_preview,
            **kwargs,
        )
    except BadRequest as e:
        if "thread not found" in str(e).lower() and kwargs:
            await context.bot.send_message(
                chat_id=chat_id(update),
                text=text,
                reply_markup=markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_preview,
            )
        else:
            raise


async def send_document(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    document,
    *,
    caption: str | None = None,
    flow: str | None = None,
) -> None:
    if not update.effective_chat:
        return
    await context.bot.send_document(
        chat_id=chat_id(update),
        document=document,
        caption=caption,
        **message_thread_kwargs(update, flow),
    )
