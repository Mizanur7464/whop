"""
Bot entry point (Phase 2 — full functionality).

What's wired here:
    * All user commands: /start, /help, /profile, /checklist, /support
    * All admin commands: /stats, /broadcast, /ban, /unban, /status
    * Central callback-query router (menu, checklist, broadcast)
    * Global error handler (logs + admin DM alert)

Run with:
    python -m bot.main
"""

from __future__ import annotations

import sys

from loguru import logger
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from bot.admin_panel import on_admin_callback
from bot.handlers import (
    admin,
    checklist,
    claim,
    copy_trading,
    form_text,
    support_channel,
    errors,
    finance,
    help as help_h,
    leave_survey,
    menu,
    onboarding,
    profile,
    start,
)
from bot import (
    copy_trading_config,
    jobs,
    onboarding_config,
    terms_config,
    support_form_config,
)
from bot.command_registry import on_startup_register_commands
from bot import group_moderation
from bot.channel_context import swallow_welcome_group_member_command
from bot.command_gate import block_until_main_group
from bot.main_group_access import on_user_joined_main_group
from config import settings
from integrations import telegram_ops

# ---------- Logging ----------

def setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
        ),
    )
    logger.add(
        "logs/bot_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="14 days",
        level=settings.log_level,
        encoding="utf-8",
    )


# ---------- Post-init: register slash commands with Telegram ----------

async def _on_startup(app: Application) -> None:
    telegram_ops.set_bot(app)
    onboarding_config.get()  # validate config at boot
    copy_trading_config.get()
    terms_config.get()
    support_form_config.get()

    await on_startup_register_commands(app)

    jobs.schedule_daily_report(app, hour_utc=8)

    me = await app.bot.get_me()
    logger.success(f"Bot connected: @{me.username} (id={me.id})")


# ---------- App factory ----------

def build_app() -> Application:
    # Default library timeout is 5s — too short on slow or blocked networks.
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .request(request)
        .post_init(_on_startup)
        .build()
    )

    private_cmds = filters.ChatType.PRIVATE & filters.COMMAND

    async def _claim_only_dm_gate(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if await block_until_main_group(update, context):
            raise ApplicationHandlerStop()

    app.add_handler(MessageHandler(private_cmds, _claim_only_dm_gate), group=-2)

    if settings.telegram_welcome_group_id:

        async def _welcome_group_command_gate(
            update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None:
            if await swallow_welcome_group_member_command(update, context):
                raise ApplicationHandlerStop()

        welcome_cmds = filters.Chat(chat_id=settings.telegram_welcome_group_id) & filters.COMMAND
        app.add_handler(
            MessageHandler(welcome_cmds, _welcome_group_command_gate),
            group=-2,
        )

    app.add_handler(CommandHandler("start", start.cmd_start))
    app.add_handler(CommandHandler("help", help_h.cmd_help))
    app.add_handler(CommandHandler("profile", profile.cmd_profile))
    app.add_handler(CommandHandler("checklist", checklist.cmd_checklist))
    app.add_handler(CommandHandler(["onboarding", "welcome"], onboarding.cmd_onboarding))
    app.add_handler(CommandHandler("claim", claim.cmd_claim))
    app.add_handler(
        CommandHandler(["support", "supportform"], support_channel.cmd_support)
    )
    app.add_handler(
        CommandHandler(["copytrading", "copy_trading"], copy_trading.cmd_copytrading)
    )
    app.add_handler(CommandHandler("admin", admin.cmd_admin))
    app.add_handler(CommandHandler("stats", admin.cmd_stats))
    app.add_handler(CommandHandler("broadcast", admin.cmd_broadcast))
    app.add_handler(CommandHandler("ban", admin.cmd_ban))
    app.add_handler(CommandHandler("unban", admin.cmd_unban))
    app.add_handler(CommandHandler("sync", admin.cmd_sync))
    app.add_handler(CommandHandler("whop_test", admin.cmd_whop_test))
    app.add_handler(CommandHandler("claims", claim.cmd_pending_claims))
    app.add_handler(CommandHandler("reload_config", admin.cmd_reload_config))
    app.add_handler(CommandHandler("airtable_check", admin.cmd_airtable_check))
    app.add_handler(CommandHandler("status", admin.cmd_status))
    app.add_handler(CommandHandler("topicid", admin.cmd_topicid))

    app.add_handler(CommandHandler("expense", finance.cmd_expense))
    app.add_handler(CommandHandler("revenue", finance.cmd_revenue))
    app.add_handler(CommandHandler("expenses", finance.cmd_expenses))
    app.add_handler(CommandHandler("pnl", finance.cmd_pnl))

    app.add_handler(
        CallbackQueryHandler(
            onboarding.on_onboarding_callback,
            pattern=r"^onb:",
            block=True,
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            copy_trading.on_copytrading_callback,
            pattern=r"^ct:",
            block=True,
        )
    )
    if settings.telegram_main_group_id:
        main_group = filters.Chat(chat_id=settings.telegram_main_group_id)
        app.add_handler(
            ChatMemberHandler(
                leave_survey.on_chat_member,
                ChatMemberHandler.CHAT_MEMBER,
            )
        )
        app.add_handler(
            ChatMemberHandler(
                on_user_joined_main_group,
                ChatMemberHandler.CHAT_MEMBER,
            )
        )
        if settings.group_moderation_enabled:
            app.add_handler(
                MessageHandler(
                    main_group & ~filters.StatusUpdate.ALL,
                    group_moderation.on_main_group_message,
                ),
                group=-1,
            )
            logger.info(
                f"Group moderation ON for main group {settings.telegram_main_group_id} "
                "(non-admin messages deleted; Members Community topic allowed)"
            )

    if settings.telegram_welcome_group_id and settings.group_moderation_enabled:
        welcome_group = filters.Chat(chat_id=settings.telegram_welcome_group_id)
        app.add_handler(
            MessageHandler(
                welcome_group & ~filters.StatusUpdate.ALL,
                group_moderation.on_welcome_group_message,
            ),
            group=-1,
        )
        logger.info(
            f"Group moderation ON for welcome group {settings.telegram_welcome_group_id} "
            "(Welcome + Notifications: admin-only)"
        )
    app.add_handler(
        CallbackQueryHandler(leave_survey.on_leave_callback, pattern=r"^lv:")
    )

    app.add_handler(MessageHandler(filters.PHOTO, onboarding.on_screenshot_photo))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, form_text.on_form_text)
    )
    app.add_handler(
        CallbackQueryHandler(
            support_channel.on_support_callback, pattern=r"^sp:", block=True
        )
    )
    app.add_handler(
        CallbackQueryHandler(on_admin_callback, pattern=r"^admin:", block=True)
    )
    app.add_handler(CallbackQueryHandler(menu.on_callback))

    app.add_error_handler(errors.on_error)
    return app


def main() -> None:
    setup_logging()
    logger.info("Booting Whop x Telegram x Airtable bot (Phase 2)")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Admin IDs: {settings.telegram_admin_ids}")

    app = build_app()
    logger.success("All handlers registered. Starting polling. Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutdown requested. Bye!")
