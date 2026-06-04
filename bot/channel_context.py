"""
Group topics = no bot replies (keeps threads clean).

Member commands in a group are ignored publicly; the bot DMs the user
when Telegram allows it.
"""

from __future__ import annotations

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from bot import texts
from bot.community_layout import (
    FLOW_COPYTRADING,
    FLOW_SUPPORT,
    FLOW_WELCOME,
    flow_label,
)
from config import settings

_FLOW_START_PAYLOAD = {
    FLOW_WELCOME: "onboarding",
    FLOW_COPYTRADING: "copytrading",
    FLOW_SUPPORT: "support",
}

# Member slash commands — never reply in group/supergroup (admins excepted).
_MEMBER_COMMANDS = frozenset(
    {
        "start",
        "onboarding",
        "welcome",
        "copytrading",
        "copy_trading",
        "support",
        "supportform",
        "help",
        "profile",
        "checklist",
        "claim",
    }
)


def is_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type == "private")


def is_group_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type in ("group", "supergroup"))


def is_main_group(update: Update) -> bool:
    gid = settings.telegram_main_group_id
    if not gid:
        return False
    chat = update.effective_chat
    return bool(chat and chat.id == gid)


def is_welcome_group(update: Update) -> bool:
    gid = settings.telegram_welcome_group_id
    if not gid:
        return False
    chat = update.effective_chat
    return bool(chat and chat.id == gid)


def _command_name(update: Update) -> str | None:
    msg = update.effective_message
    if not msg or not msg.text or not msg.text.startswith("/"):
        return None
    token = msg.text.split()[0]
    return token.lstrip("/").split("@")[0].lower()


async def _try_delete_command_message(update: Update) -> None:
    """Remove /command from the group so others don't see it (needs admin rights)."""
    msg = update.effective_message
    if not msg:
        return
    try:
        await msg.delete()
    except BadRequest:
        pass


async def ping_user_dm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    flow: str,
    command: str,
    body: str | None = None,
) -> None:
    """Send flow invite only in private DM — nothing in the group."""
    user = update.effective_user
    if not user:
        return

    me = await context.bot.get_me()
    payload = _FLOW_START_PAYLOAD.get(flow, "onboarding")
    url = f"https://t.me/{me.username}?start={payload}"
    label = flow_label(flow)
    text = body or texts.DM_FLOW_INVITE.format(
        flow_label=label,
        command=command,
    )
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.BTN_OPEN_BOT_PRIVATE, url=url)]]
    )
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=text,
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    except Forbidden:
        logger.info(
            f"Cannot DM user {user.id} — they must open @{me.username} in private chat first"
        )
    except Exception as e:
        logger.warning(f"DM invite failed for user {user.id}: {e}")


async def ensure_private_dm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    flow: str,
    command: str,
) -> bool:
    """Return True only in private chat; in groups → silent + DM invite."""
    if is_private_chat(update):
        return True

    await _try_delete_command_message(update)
    await ping_user_dm(update, context, flow=flow, command=command)
    return False


async def block_if_group_chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    flow: str,
    command: str,
) -> bool:
    """Callbacks in groups: dismiss silently (no group message)."""
    if is_private_chat(update):
        return False
    if update.callback_query:
        await update.callback_query.answer()
    return True


async def silence_group_member_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    If a member used a flow command in a group, swallow it (no public reply).

    Returns True when the handler should stop.
    """
    if is_private_chat(update):
        return False

    name = _command_name(update)
    if name not in _MEMBER_COMMANDS:
        return False

    flow = FLOW_WELCOME
    if name in ("copytrading", "copy_trading"):
        flow = FLOW_COPYTRADING
    elif name in ("support", "supportform"):
        flow = FLOW_SUPPORT

    await _try_delete_command_message(update)
    await ping_user_dm(update, context, flow=flow, command=name.replace("_", ""))
    return True


async def ensure_welcome_context(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    return await ensure_private_dm(
        update, context, flow=FLOW_WELCOME, command="start"
    )


async def ensure_copytrading_channel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    return await ensure_private_dm(
        update, context, flow=FLOW_COPYTRADING, command="copytrading"
    )


async def ensure_support_channel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    return await ensure_private_dm(
        update, context, flow=FLOW_SUPPORT, command="support"
    )
