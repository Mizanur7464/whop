"""
Reusable decorators for handlers.

Usage:
    @admin_only
    async def cmd_broadcast(update, context): ...
"""

from __future__ import annotations

from functools import wraps
from typing import Awaitable, Callable

from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes

from bot import texts
from bot.telegram_utils import safe_answer_callback
from config import settings

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def is_admin(user_id: int) -> bool:
    return user_id in settings.telegram_admin_ids


def admin_only(handler: Handler) -> Handler:
    """Reject non-admin callers with a polite message."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user or not is_admin(user.id):
            logger.warning(
                f"Blocked non-admin {user.id if user else '?'} from {handler.__name__}"
            )
            if update.callback_query:
                await safe_answer_callback(
                    update.callback_query, texts.UNAUTHORIZED, show_alert=True
                )
            elif update.message:
                await update.message.reply_text(texts.UNAUTHORIZED)
            return
        await handler(update, context)

    return wrapper


def log_call(handler: Handler) -> Handler:
    """Log entry into a handler for easier debugging."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        uid = user.id if user else "?"
        uname = f"@{user.username}" if user and user.username else "no-username"
        logger.debug(f"→ {handler.__name__} | user={uid} {uname}")
        await handler(update, context)

    return wrapper
