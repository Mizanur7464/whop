"""Small Telegram API helpers."""

from __future__ import annotations

from loguru import logger
from telegram import Bot, CallbackQuery, Message
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError


def is_stale_callback_error(err: BaseException) -> bool:
    """True when the user tapped an expired inline button."""
    if not isinstance(err, BadRequest):
        return False
    msg = str(err).lower()
    return "query is too old" in msg or "query id is invalid" in msg


async def safe_send_message(
    bot: Bot,
    chat_id: int,
    text: str,
    *,
    parse_mode: str | None = ParseMode.MARKDOWN,
    **kwargs,
) -> Message | None:
    """Send a DM; retry without Markdown if entities fail. Never fail silently."""
    try:
        return await bot.send_message(
            chat_id, text, parse_mode=parse_mode, **kwargs
        )
    except (BadRequest, TelegramError) as e:
        err = str(e).lower()
        if parse_mode is not None and (
            "can't parse entities" in err or "parse" in err
        ):
            logger.debug(f"safe_send: retry without parse_mode to {chat_id}")
            try:
                return await bot.send_message(
                    chat_id, text, parse_mode=None, **kwargs
                )
            except TelegramError as e2:
                logger.error(f"safe_send: plain send failed to {chat_id}: {e2}")
                return None
        logger.error(f"safe_send: failed to {chat_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"safe_send: unexpected error to {chat_id}: {e}")
        return None


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
