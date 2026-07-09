"""Welcome DM when someone joins the Fusion lobby (welcome) group."""

from __future__ import annotations

from loguru import logger
from telegram import ChatMemberUpdated, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from bot.decorators import is_admin
from config import settings
from integrations import telegram_ops

LOBBY_WELCOME_TEXT = (
    "Hi welcome to Fusion, good to have you onboard. "
    "Click on the username and reach out to Calum (@CDFX_fusion) "
    "so he can help you with the onboarding and setting everything up"
)

_JOIN_STATUSES = frozenset(
    {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.RESTRICTED,
    }
)


async def on_user_joined_lobby_group(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not settings.telegram_lobby_welcome_dm_enabled:
        return

    cm: ChatMemberUpdated | None = update.chat_member
    if not cm or cm.chat.id != settings.telegram_welcome_group_id:
        return

    old = cm.old_chat_member.status
    new = cm.new_chat_member.status
    if new not in _JOIN_STATUSES:
        return
    if old in _JOIN_STATUSES:
        return

    user = cm.new_chat_member.user
    if not user or user.is_bot or is_admin(user.id):
        return

    text = (settings.telegram_lobby_welcome_dm_text or "").strip() or LOBBY_WELCOME_TEXT
    ok = await telegram_ops.dm(user.id, text, parse_mode=None)
    if ok:
        logger.info(f"lobby_welcome: sent join DM to user {user.id}")
    else:
        logger.debug(f"lobby_welcome: DM failed for user {user.id} (blocked bot?)")
