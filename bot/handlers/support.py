"""/support — show contact info."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot import keyboards, texts
from bot.decorators import log_call


@log_call
async def cmd_support(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        texts.SUPPORT_TEXT,
        reply_markup=keyboards.back_only(),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
