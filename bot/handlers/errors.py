"""
Global error handler.

* Logs the full traceback to logs/bot_*.log
* Notifies all admins via DM (so production issues are visible fast)
* Sends a friendly message to the user whose action crashed
"""

from __future__ import annotations

import html
import traceback

from loguru import logger
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot import texts
from bot.telegram_utils import is_stale_callback_error
from config import settings


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if err and is_stale_callback_error(err):
        logger.debug(f"Stale inline button click ignored: {err}")
        return

    logger.opt(exception=err).error("Unhandled exception in handler")

    tb_lines = traceback.format_exception(type(err), err, err.__traceback__ if err else None)
    tb_text = "".join(tb_lines)[-3000:]  # keep last 3 KB

    update_str = ""
    if isinstance(update, Update):
        try:
            update_str = update.to_json()[:1000]
        except Exception:
            update_str = repr(update)[:1000]

    admin_alert = (
        "🚨 *Bot Error*\n\n"
        f"`{html.escape(str(err))[:300]}`\n\n"
        "*Trace (tail):*\n"
        f"```\n{html.escape(tb_text)}\n```"
    )

    for admin_id in settings.telegram_admin_ids:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_alert,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.warning(f"Could not alert admin {admin_id}: {e}")

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(texts.ERROR_GENERIC)
        except Exception:
            pass
