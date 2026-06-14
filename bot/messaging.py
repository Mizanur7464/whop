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
) -> bool:
    """Send a document; return True on success (False so callers can fall back to URL)."""
    msg = await _send_document_message(
        update,
        context,
        document,
        caption=caption,
        flow=flow,
    )
    return msg is not None


async def _send_document_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    document,
    *,
    caption: str | None = None,
    flow: str | None = None,
):
    """Send a document; return the Message on success or None."""
    if not update.effective_chat:
        return None
    thread_kwargs = message_thread_kwargs(update, flow)
    cid = chat_id(update)

    async def _attempt(extra: dict | None = None):
        return await context.bot.send_document(
            chat_id=cid,
            document=document,
            caption=caption,
            **(extra if extra is not None else thread_kwargs),
        )

    try:
        return await _attempt()
    except BadRequest as e:
        err = str(e).lower()
        if thread_kwargs and "thread not found" in err:
            try:
                return await _attempt(extra={})
            except BadRequest:
                return None
        return None
    except Exception:
        return None


async def send_cached_pdf(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pdf_path,
    *,
    caption: str | None = None,
    flow: str | None = None,
) -> bool:
    """Send a PDF using a cached Telegram file_id when available."""
    from pathlib import Path

    from bot import pdf_cache

    path = Path(pdf_path)
    if not path.is_file():
        return False

    cached_id = pdf_cache.get_file_id(path)
    if cached_id:
        msg = await _send_document_message(
            update,
            context,
            cached_id,
            caption=caption,
            flow=flow,
        )
        if msg:
            return True
        logger.warning(f"send_cached_pdf: cached file_id failed for {path.name}")

    msg = await _send_document_message(
        update,
        context,
        path,
        caption=caption,
        flow=flow,
    )
    if msg and msg.document:
        pdf_cache.set_file_id(path, msg.document.file_id)
        return True
    return False
