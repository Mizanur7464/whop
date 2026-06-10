"""
Register Telegram slash-command menus (BotFather scopes).

Buyer layout:
    * Private DM → /onboarding, /copytrading, /support, /claim
    * Group → same short list (no /start or /help in menu)
    * Copy Trading topic          → /copytrading
    * Support topic               → /support
    * Admin DM                    → full admin list
"""

from __future__ import annotations

from loguru import logger
from telegram import (
    Bot,
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    MenuButtonCommands,
    MenuButtonDefault,
)
from telegram.ext import Application

from bot.community_layout import main_group_id, uses_topics_mode
from config import settings

# ---------- Command menus (what users see when typing /) ----------

# Member menus: /start still works if typed, but hidden from "/" list (same as onboarding).
MEMBER_DM_COMMANDS: list[BotCommand] = [
    BotCommand("onboarding", "Begin welcome onboarding"),
    BotCommand("copytrading", "Copy trading setup"),
    BotCommand("support", "Support contact form"),
    BotCommand("claim", "Link your Whop purchase"),
]

PRIVATE_COMMANDS = MEMBER_DM_COMMANDS

CLAIM_ONLY_COMMANDS: list[BotCommand] = [
    BotCommand("claim", "Link your Whop access"),
    BotCommand("onboarding", "Complete welcome onboarding"),
]

WELCOME_CHANNEL_COMMANDS: list[BotCommand] = [
    BotCommand("onboarding", "Begin welcome onboarding"),
]

COPYTRADING_CHANNEL_COMMANDS: list[BotCommand] = [
    BotCommand("copytrading", "Copy trading setup"),
]

SUPPORT_CHANNEL_COMMANDS: list[BotCommand] = [
    BotCommand("support", "Contact the team"),
]

# One menu for the whole forum group — keep minimal (flows run in bot DM).
DEV_GROUP_COMMANDS: list[BotCommand] = [
    BotCommand("onboarding", "Welcome onboarding"),
    BotCommand("copytrading", "Copy trading setup"),
    BotCommand("support", "Support form"),
]

ADMIN_COMMANDS: list[BotCommand] = MEMBER_DM_COMMANDS + [
    BotCommand("admin", "Admin control panel"),
    BotCommand("start", "Begin welcome onboarding"),
    BotCommand("help", "Command list"),
    BotCommand("copytrading", "Copy trading setup (test)"),
    BotCommand("support", "Support form (test)"),
    BotCommand("profile", "View membership info"),
    BotCommand("checklist", "Onboarding checklist"),
    BotCommand("stats", "Live member stats"),
    BotCommand("broadcast", "Message all members"),
    BotCommand("ban", "Remove a user"),
    BotCommand("unban", "Reinstate a user"),
    BotCommand("sync", "Pull memberships from Whop"),
    BotCommand("whop_test", "Ping the Whop API"),
    BotCommand("claims", "List pending claims"),
    BotCommand("reload_config", "Reload JSON configs"),
    BotCommand("expense", "Log expense to Airtable"),
    BotCommand("revenue", "Revenue summary"),
    BotCommand("expenses", "Expense summary"),
    BotCommand("pnl", "Profit & loss summary"),
    BotCommand("airtable_check", "Validate Airtable schema"),
    BotCommand("airtable_setup", "Add missing Airtable columns"),
    BotCommand("status", "Build status"),
    BotCommand("topicid", "Show group + topic IDs for .env"),
]


def _channel_pairs() -> list[tuple[int | None, list[BotCommand], str]]:
    return [
        (settings.welcome_channel_id, WELCOME_CHANNEL_COMMANDS, "Welcome"),
        (settings.copy_trading_channel_id, COPYTRADING_CHANNEL_COMMANDS, "Copy Trading"),
        (settings.support_channel_id, SUPPORT_CHANNEL_COMMANDS, "Support"),
    ]


def _any_channel_configured() -> bool:
    return any(cid for cid, _, _ in _channel_pairs())


async def ensure_menu_button(bot: Bot, *, chat_id: int | None = None) -> None:
    kwargs: dict = {"menu_button": MenuButtonCommands()}
    if chat_id is not None:
        kwargs["chat_id"] = chat_id
    await bot.set_chat_menu_button(**kwargs)


async def clear_welcome_group_command_menu(bot: Bot) -> None:
    """
    Hide the / command list in TELEGRAM_WELCOME_GROUP_ID only.

    Members should use the pinned Whop link; DM keeps the full command menu.
    """
    gid = settings.telegram_welcome_group_id
    if not gid:
        return
    try:
        await bot.set_my_commands([], scope=BotCommandScopeChat(chat_id=gid))
        await bot.set_chat_menu_button(chat_id=gid, menu_button=MenuButtonDefault())
        logger.info(f"Commands: hidden slash menu in Welcome group (chat_id={gid})")
    except Exception as e:
        logger.warning(f"Commands: could not clear Welcome group menu ({gid}): {e}")


async def register_all_commands(bot: Bot) -> None:
    await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeDefault())
    await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    logger.info(
        f"Commands: registered private menu ({len(PRIVATE_COMMANDS)} commands)"
    )

    gid = main_group_id()
    if uses_topics_mode() and gid:
        try:
            await bot.set_my_commands(
                DEV_GROUP_COMMANDS, scope=BotCommandScopeChat(chat_id=gid)
            )
            await ensure_menu_button(bot, chat_id=gid)
            logger.info(f"Commands: registered community group menu (chat_id={gid})")
        except Exception as e:
            logger.warning(f"Commands: could not set community group menu: {e}")
    else:
        configured = 0
        for chat_id, commands, label in _channel_pairs():
            if not chat_id:
                continue
            try:
                await bot.set_my_commands(
                    commands, scope=BotCommandScopeChat(chat_id=chat_id)
                )
                await ensure_menu_button(bot, chat_id=chat_id)
                configured += 1
                logger.info(
                    f"Commands: registered {label} channel menu (chat_id={chat_id})"
                )
            except Exception as e:
                logger.warning(
                    f"Commands: could not set {label} channel ({chat_id}): {e}"
                )

    if not uses_topics_mode() and not _any_channel_configured():
        try:
            await bot.set_my_commands(
                DEV_GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats()
            )
            logger.info(
                "Commands: no channel IDs in .env — registered dev menu for all groups"
            )
        except Exception as e:
            logger.warning(f"Commands: could not set group dev menu: {e}")

    for admin_id in settings.telegram_admin_ids:
        try:
            await bot.set_my_commands(
                ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id)
            )
            await ensure_menu_button(bot, chat_id=admin_id)
            logger.info(f"Commands: registered admin menu for {admin_id}")
        except Exception as e:
            logger.warning(f"Commands: could not set admin menu for {admin_id}: {e}")

    await clear_welcome_group_command_menu(bot)

    try:
        await ensure_menu_button(bot)
        logger.info("Commands: global menu button set to command list")
    except Exception as e:
        logger.warning(f"Commands: could not set global menu button: {e}")


async def refresh_member_dm_commands(
    bot: Bot,
    user_id: int,
    *,
    is_admin: bool = False,
    claim_only: bool = False,
) -> None:
    """Per-user private menu (claim-only vs full member list)."""
    if is_admin:
        commands = ADMIN_COMMANDS
    elif claim_only:
        commands = CLAIM_ONLY_COMMANDS
    else:
        commands = PRIVATE_COMMANDS
    await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=user_id))
    await ensure_menu_button(bot, chat_id=user_id)


async def refresh_chat_commands(
    bot: Bot,
    chat_id: int,
    *,
    is_admin: bool = False,
    claim_only: bool = False,
) -> None:
    if chat_id == settings.telegram_welcome_group_id and not is_admin:
        await clear_welcome_group_command_menu(bot)
        return
    await refresh_member_dm_commands(
        bot, chat_id, is_admin=is_admin, claim_only=claim_only
    )


async def on_startup_register_commands(app: Application) -> None:
    await register_all_commands(app.bot)
