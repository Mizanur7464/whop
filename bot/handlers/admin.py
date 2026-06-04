"""
Admin-only commands: /stats, /broadcast, /ban, /unban, /status.

All commands gated by @admin_only — non-admins get a polite refusal.
"""

from __future__ import annotations

from loguru import logger
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from airtable import sync as airtable_sync
from airtable.client import AirtableClient
from bot.community_access import community_chat_ids
from integrations import telegram_ops
from bot import (
    copy_trading_config,
    keyboards,
    terms_config,
    onboarding_config,
    support_form_config,
    storage,
    texts,
)
from bot.admin_panel import show_admin_panel
from bot.decorators import admin_only, is_admin, log_call
from integrations import plan_mapping
from integrations.whop_api import WhopAPIError, WhopClient


# ---------- /admin ----------

@admin_only
@log_call
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin dashboard — all commands and features in one place."""
    await show_admin_panel(update, context)


# ---------- /stats ----------

@admin_only
@log_call
async def cmd_stats(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    s = storage.stats()
    body = texts.STATS_TEMPLATE.format(
        total=s["total"],
        active=s["active"],
        banned=s["banned"],
        new_today=s["new_today"],
        phase="2 — Telegram Bot Build",
    )
    await update.message.reply_text(body, parse_mode=ParseMode.MARKDOWN)


# ---------- /broadcast ----------

@admin_only
@log_call
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Two-step broadcast: stage the message, then confirm via inline buttons."""
    if not context.args:
        await update.message.reply_text(
            texts.BROADCAST_USAGE, parse_mode=ParseMode.MARKDOWN
        )
        return

    message = " ".join(context.args)
    context.user_data["pending_broadcast"] = message

    targets = storage.list_active_user_ids()
    preview = message if len(message) < 300 else message[:300] + "…"
    await update.message.reply_text(
        texts.BROADCAST_CONFIRM.format(count=len(targets), preview=preview),
        reply_markup=keyboards.broadcast_confirm(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------- /ban ----------

@admin_only
@log_call
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            texts.BAN_USAGE, parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "User ID must be a number.", parse_mode=ParseMode.MARKDOWN
        )
        return

    result = storage.set_status(target_id, "banned")
    if not result:
        await update.message.reply_text(
            texts.BAN_FAIL.format(user_id=target_id, reason="not found in storage"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    logger.info(f"Admin {update.effective_user.id} banned user {target_id}")
    await airtable_sync.member_status_changed(target_id, "banned")
    chats = community_chat_ids()
    if chats:
        await telegram_ops.revoke_access(
            target_id, chats, reason="banned by admin"
        )
    await update.message.reply_text(
        texts.BAN_SUCCESS.format(user_id=target_id),
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------- /unban ----------

@admin_only
@log_call
async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            texts.UNBAN_USAGE, parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "User ID must be a number.", parse_mode=ParseMode.MARKDOWN
        )
        return

    result = storage.set_status(target_id, "active")
    if not result:
        await update.message.reply_text(
            f"User `{target_id}` not found.", parse_mode=ParseMode.MARKDOWN
        )
        return

    await airtable_sync.member_status_changed(target_id, "active")

    logger.info(f"Admin {update.effective_user.id} unbanned user {target_id}")
    await update.message.reply_text(
        texts.UNBAN_SUCCESS.format(user_id=target_id),
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------- /topicid (forum topics setup) ----------

async def _can_run_topicid(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    user = update.effective_user
    if not user:
        return False
    if is_admin(user.id):
        return True
    chat = update.effective_chat
    if chat and chat.type in ("group", "supergroup"):
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("creator", "administrator")
    return False


@log_call
async def cmd_topicid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with chat_id and message_thread_id for .env setup."""
    if not await _can_run_topicid(update, context):
        await update.message.reply_text(texts.UNAUTHORIZED)
        return
    msg = update.message
    chat = update.effective_chat
    if not msg or not chat:
        return
    thread = msg.message_thread_id
    topic_lines = [
        ("TELEGRAM_TOPIC_WELCOME", "Welcome"),
        ("TELEGRAM_TOPIC_COPYTRADING", "Copy Trading"),
        ("TELEGRAM_TOPIC_SUPPORT", "Support"),
        ("TELEGRAM_TOPIC_SIGNALS", "Signals"),
        ("TELEGRAM_TOPIC_EDUCATION", "Education"),
        ("TELEGRAM_TOPIC_NOTIFICATIONS", "Daily Notifications"),
        ("TELEGRAM_TOPIC_PNL", "PnL (optional)"),
    ]
    if thread:
        keys_block = "\n".join(
            f"<code>{key}=</code>  <i>{label}</i>" for key, label in topic_lines
        )
        topic_block = (
            f"<b>This topic ID:</b> <code>{thread}</code>\n"
            f"Example: <code>TELEGRAM_TOPIC_NOTIFICATIONS={thread}</code>"
        )
    else:
        keys_block = "\n".join(
            f"<code>{key}=</code>  <i>{label}</i>" for key, label in topic_lines
        )
        topic_block = (
            "<i>Open a named topic (not General), then run /topicid again.</i>"
        )
    await update.message.reply_text(
        "📌 <b>IDs for .env</b>\n\n"
        f"TELEGRAM_MAIN_GROUP_ID=<code>{chat.id}</code>\n\n"
        f"{topic_block}\n\n"
        "<b>Topic keys (pick one per topic):</b>\n"
        f"{keys_block}",
        parse_mode=ParseMode.HTML,
    )


# ---------- /status ----------

@admin_only
@log_call
async def cmd_status(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current build phase progress."""
    body = (
        "📊 *Build Status*\n\n"
        "✅ Phase 1 — Setup & Requirements\n"
        "✅ Phase 2 — Telegram Bot Build\n"
        "✅ Phase 3 — Whop Integration\n"
        "✅ Phase 4 — Onboarding + Checklist\n"
        "✅ Phase 5 — Airtable CRM\n"
        "✅ Phase 6 — Deployment & Handover\n\n"
        "🎉 *All phases complete — production ready*"
    )
    await update.message.reply_text(body, parse_mode=ParseMode.MARKDOWN)


# ---------- /airtable_check ----------

@admin_only
@log_call
async def cmd_airtable_check(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Verify the Airtable base has all required tables + fields."""
    await update.message.reply_text("Probing Airtable base…")

    client = AirtableClient()
    if not client.enabled:
        try:
            import pyairtable  # noqa: F401
        except ImportError:
            await update.message.reply_text(
                "❌ `pyairtable` is not installed.\n\n"
                "Run: `pip install -r requirements.txt` then restart the bot.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        await update.message.reply_text(
            "❌ Airtable not configured. Set `AIRTABLE_API_KEY` and "
            "`AIRTABLE_BASE_ID` in `.env`, then restart the bot.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    report = await client.validate_schema()

    lines = ["*Airtable Schema Check*", ""]
    for key in ("members", "payments", "expenses", "checklist"):
        info = report.get(key, {})
        icon = "✅" if info.get("ok") else "❌"
        table = info.get("table", key)
        note = info.get("note") or info.get("error")
        missing = info.get("missing") or []
        lines.append(f"{icon} *{table}*")
        if missing:
            lines.append(f"   Missing fields: `{', '.join(missing)}`")
        if note:
            lines.append(f"   _{note}_")

    overall = "✅ All good" if report.get("all_ok") else "⚠️ Issues found"
    lines.append("")
    lines.append(f"*Overall:* {overall}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ---------- /reload_config ----------

@admin_only
@log_call
async def cmd_reload_config(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Hot-reload data/onboarding.json without restarting the bot."""
    try:
        cfg = onboarding_config.reload()
        ct_cfg = copy_trading_config.reload()
        terms_cfg = terms_config.reload()
        sp_cfg = support_form_config.reload()
    except Exception as e:
        await update.message.reply_text(
            f"❌ Reload failed: `{e}`", parse_mode=ParseMode.MARKDOWN
        )
        return

    body = (
        "✅ *Configs reloaded*\n\n"
        f"*Onboarding* v{cfg.version} — {len(cfg.checklist_items)} checklist items, "
        f"reminder {cfg.reminder_hours}h (max {cfg.max_reminders})\n"
        f"*Copy trading* v{ct_cfg.version} — {len(ct_cfg.platforms)} platforms, "
        f"{len(ct_cfg.checklist_items)} checklist items\n"
        f"*Terms* v{terms_cfg.version} — {terms_cfg.message[:40]}…\n"
        f"*Support form* v{sp_cfg.version} — {len(sp_cfg.form_questions)} questions"
    )
    await update.message.reply_text(body, parse_mode=ParseMode.MARKDOWN)


# ---------- /whop_test ----------

@admin_only
@log_call
async def cmd_whop_test(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Quick sanity check that the Whop API key works."""
    await update.message.reply_text("Pinging Whop API…")
    try:
        async with WhopClient() as client:
            me = await client.get_me()
        body = (
            "✅ *Whop API reachable*\n\n"
            f"```\n{str(me)[:600]}\n```"
        )
    except WhopAPIError as e:
        body = f"❌ Whop API error {e.status}\n\n`{str(e)[:300]}`"
    except Exception as e:
        body = f"❌ Unexpected error: `{e}`"

    await update.message.reply_text(body, parse_mode=ParseMode.MARKDOWN)


# ---------- /sync ----------

@admin_only
@log_call
async def cmd_sync(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Pull all currently-valid memberships from Whop and reconcile with
    local storage. Useful after deploying, or if a webhook is missed.
    """
    await update.message.reply_text("Syncing memberships from Whop…")

    fetched = 0
    linked = 0
    pending = 0
    try:
        async with WhopClient() as client:
            memberships = await client.iter_memberships(valid=True)
    except WhopAPIError as e:
        await update.message.reply_text(
            f"❌ Whop API error: {e.status}\n`{str(e)[:300]}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    for m in memberships:
        fetched += 1
        whop_user = m.get("user_id") or (m.get("user") or {}).get("id")
        product_id = m.get("product_id") or (m.get("product") or {}).get("id")
        if not whop_user:
            continue

        plan = plan_mapping.resolve_plan_name(product_id)
        existing_tg = storage.get_telegram_id_for_whop_user(whop_user)
        if existing_tg:
            storage.upsert_user(
                existing_tg,
                whop_user_id=whop_user,
                whop_membership_id=m.get("id"),
                plan=plan,
                status="active",
            )
            linked += 1
        else:
            pending += 1

    body = (
        "🔄 *Sync complete*\n\n"
        f"• Memberships fetched: *{fetched}*\n"
        f"• Already linked + refreshed: *{linked}*\n"
        f"• Awaiting `/claim` link: *{pending}*"
    )
    await update.message.reply_text(body, parse_mode=ParseMode.MARKDOWN)
