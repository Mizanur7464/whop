"""
Gate bot commands until the user has joined TELEGRAM_MAIN_GROUP_ID.
"""

from __future__ import annotations

import asyncio

from loguru import logger
from telegram import Bot
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from bot.command_registry import refresh_member_dm_commands
from bot.decorators import is_admin
from config import settings

_IN_MAIN_STATUSES = frozenset(
    {"member", "administrator", "creator", "restricted"}
)


_CHAT_MEMBER_TIMEOUT_SEC = 8.0


async def user_in_main_group(bot: Bot, user_id: int) -> bool:
    """True if user is currently a member of the main community supergroup."""
    gid = settings.telegram_main_group_id
    if not gid:
        return True
    try:
        member = await asyncio.wait_for(
            bot.get_chat_member(chat_id=gid, user_id=user_id),
            timeout=_CHAT_MEMBER_TIMEOUT_SEC,
        )
        return member.status in _IN_MAIN_STATUSES
    except asyncio.TimeoutError:
        logger.warning(
            f"main_group_access: get_chat_member timed out for user={user_id} "
            f"(group={gid}) — treating as not joined"
        )
        return False
    except BadRequest as e:
        err = str(e).lower()
        if "user not found" in err or "participant_id_invalid" in err:
            return False
        logger.warning(f"main_group_access: get_chat_member({user_id}): {e}")
        return False
    except TelegramError as e:
        logger.warning(f"main_group_access: get_chat_member({user_id}): {e}")
        return False


async def needs_claim_only_menu(bot: Bot, user_id: int) -> bool:
    """Hide onboarding/support/etc. until the user joins the main group."""
    if is_admin(user_id):
        return False
    return not await user_in_main_group(bot, user_id)


async def refresh_commands_for_user(
    bot: Bot, user_id: int, *, is_admin_user: bool | None = None
) -> None:
    """Set / menu to claim-only or full member list for this private chat."""
    admin_flag = is_admin_user if is_admin_user is not None else is_admin(user_id)
    claim_only = False
    if not admin_flag:
        claim_only = await needs_claim_only_menu(bot, user_id)
    await refresh_member_dm_commands(
        bot, user_id, is_admin=admin_flag, claim_only=claim_only
    )


async def on_user_joined_main_group(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Unlock full command menu when someone joins the main group."""
    cm = getattr(update, "chat_member", None)
    if not cm or cm.chat.id != settings.telegram_main_group_id:
        return
    user = cm.new_chat_member.user
    if not user or cm.new_chat_member.status not in _IN_MAIN_STATUSES:
        return
    if is_admin(user.id):
        return
    logger.info(f"main_group_access: user {user.id} joined main — unlocking commands")
    await refresh_commands_for_user(context.bot, user.id)
