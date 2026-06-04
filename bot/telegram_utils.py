"""Small Telegram API helpers."""

from __future__ import annotations

from loguru import logger
from telegram import CallbackQuery
from telegram.error import BadRequest


def is_stale_callback_error(err: BaseException) -> bool:
    """True when the user tapped an expired inline button."""
    if not isinstance(err, BadRequest):
        return False
    msg = str(err).lower()
    return "query is too old" in msg or "query id is invalid" in msg


async def safe_answer_callback(
    query: CallbackQuery | None,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    """Acknowledge a button press; ignore stale/expired queries silently."""
    if query is None:
        return
    try:
        await query.answer(text=text, show_alert=show_alert)
    except BadRequest as e:
        if is_stale_callback_error(e):
            logger.debug(f"Stale callback query ignored: {e}")
            return
        raise
