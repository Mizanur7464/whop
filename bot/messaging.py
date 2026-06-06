"""Thread-aware Telegram sends for forum (topics) groups."""

from __future__ import annotations

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.community_layout import message_thread_kwargs
from bot.telegram_utils import is_markdown_parse_error


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
    thread_kwargs = message_thread_kwargs(update, flow)
    cid = chat_id(update)

    async def _attempt(
        *,
        mode: str | None = parse_mode,
        extra: dict | None = None,
    ) -> None:
        await context.bot.send_message(
            chat_id=cid,
            text=text,
            reply_markup=markup,
            parse_mode=mode,
            disable_web_page_preview=disable_preview,
            **(extra if extra is not None else thread_kwargs),
        )

    try:
        await _attempt()
    except BadRequest as e:
        err = str(e).lower()
        if thread_kwargs and "thread not found" in err:
            await _attempt(extra={})
            return
        if parse_mode is not None and is_markdown_parse_error(e):
            await _attempt(mode=None)
            return
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
