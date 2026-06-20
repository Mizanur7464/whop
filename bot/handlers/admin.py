"""
Admin-only commands: /stats, /broadcast, /ban, /unban, /status.

All commands gated by @admin_only — non-admins get a polite refusal.
"""

from __future__ import annotations

import html

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
from config import settings
from integrations import plan_mapping
from integrations.whop_api import WhopAPIError, WhopClient
from integrations.whop_member_profile import profile_from_membership


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
    chat_id = chat.id
    is_welcome = chat_id == settings.telegram_welcome_group_id
    is_main = chat_id == settings.telegram_main_group_id

    if is_welcome:
        group_name = "Welcome group (Fusion Strategy Members entry)"
        topic_lines = [
            (
                "TELEGRAM_WELCOME_GROUP_TOPIC_MEMBERS_COMMUNITY",
                "Members Community (members chat OK, no links)",
            ),
            (
                "TELEGRAM_WELCOME_GROUP_TOPIC_SIGNUP_SUPPORT",
                "Sign Up Support (members chat OK, no links)",
            ),
            (
                "TELEGRAM_WELCOME_GROUP_TOPIC_SIGNUP_INSTRUCTIONS",
                "Sign Up Instructions (admin-only)",
            ),
            ("TELEGRAM_WELCOME_GROUP_TOPIC_RESULTS", "Results (admin-only)"),
            ("TELEGRAM_WELCOME_GROUP_TOPIC_FEEDBACK", "Feedback (admin-only)"),
            ("TELEGRAM_WELCOME_GROUP_TOPIC_WELCOME", "Welcome (admin-only)"),
            (
                "TELEGRAM_WELCOME_GROUP_TOPIC_NOTIFICATIONS",
                "Notifications (admin-only)",
            ),
        ]
        group_env = f"TELEGRAM_WELCOME_GROUP_ID=<code>{chat_id}</code>"
    elif is_main:
        group_name = "Main community group"
        topic_lines = [
            ("TELEGRAM_TOPIC_TRADING_TALKS", "Trading Talks (admin-only)"),
            (
                "TELEGRAM_TOPIC_MEMBERS_RESULTS",
                "Members Results (member chat OK, no links)",
            ),
            ("TELEGRAM_TOPIC_SIGNALS", "Signals (admin-only)"),
            ("TELEGRAM_TOPIC_COPYTRADING", "Copy Trading (admin-only)"),
            ("TELEGRAM_TOPIC_SUPPORT", "Support (admin-only)"),
            ("TELEGRAM_TOPIC_NOTIFICATIONS", "Daily Notifications (admin-only)"),
            ("TELEGRAM_TOPIC_PNL", "PnL (optional, admin-only)"),
            (
                "TELEGRAM_TOPIC_EDUCATION",
                "Legacy — do not use for member chat (moved to welcome group)",
            ),
        ]
        group_env = f"TELEGRAM_MAIN_GROUP_ID=<code>{chat_id}</code>"
    else:
        group_name = "This group"
        topic_lines = [
            ("TELEGRAM_MAIN_GROUP_ID or TELEGRAM_WELCOME_GROUP_ID", "Set chat id first"),
        ]
        group_env = f"Chat ID: <code>{chat_id}</code>"
    if thread:
        keys_block = "\n".join(
            f"<code>{key}=</code>  <i>{label}</i>" for key, label in topic_lines
        )
        topic_block = (
            f"<b>This topic ID:</b> <code>{thread}</code>\n"
            f"Example: <code>{topic_lines[0][0]}={thread}</code>"
        )
    else:
        keys_block = "\n".join(
            f"<code>{key}=</code>  <i>{label}</i>" for key, label in topic_lines
        )
        topic_block = (
            "<i>Open a named topic (not General), then run /topicid again.</i>"
        )
    from bot import group_moderation

    mod_block = group_moderation.moderation_summary().replace("\n", "\n• ")
    await update.message.reply_text(
        f"📌 <b>IDs for .env — {group_name}</b>\n\n"
        f"{group_env}\n\n"
        f"{topic_block}\n\n"
        "<b>Topic keys (pick one per topic):</b>\n"
        f"{keys_block}\n\n"
        "<b>Group moderation:</b>\n"
        f"• {mod_block}",
        parse_mode=ParseMode.HTML,
    )


@log_call
async def cmd_create_members_topic(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Create a forum topic in the welcome group (default: Members Community)."""
    if not await _can_run_topicid(update, context):
        await update.message.reply_text(texts.UNAUTHORIZED)
        return

    gid = settings.telegram_welcome_group_id
    env_key = "TELEGRAM_WELCOME_GROUP_TOPIC_MEMBERS_COMMUNITY"
    if not gid:
        await update.message.reply_text(
            "Set TELEGRAM_WELCOME_GROUP_ID in .env first."
        )
        return

    name = " ".join(context.args).strip() if context.args else "Members Community"
    name_lower = name.lower()
    if "sign up support" in name_lower or name_lower == "signup support":
        env_key = "TELEGRAM_WELCOME_GROUP_TOPIC_SIGNUP_SUPPORT"
    elif "sign up instructions" in name_lower or name_lower == "signup instructions":
        env_key = "TELEGRAM_WELCOME_GROUP_TOPIC_SIGNUP_INSTRUCTIONS"
    elif name_lower == "results":
        env_key = "TELEGRAM_WELCOME_GROUP_TOPIC_RESULTS"
    elif name_lower == "feedback":
        env_key = "TELEGRAM_WELCOME_GROUP_TOPIC_FEEDBACK"
    elif "trading talks" in name_lower:
        gid = settings.telegram_main_group_id
        env_key = "TELEGRAM_TOPIC_TRADING_TALKS"
        if not gid:
            await update.message.reply_text(
                "Set TELEGRAM_MAIN_GROUP_ID in .env for Trading Talks."
            )
            return
    elif "members results" in name_lower:
        gid = settings.telegram_main_group_id
        env_key = "TELEGRAM_TOPIC_MEMBERS_RESULTS"
        if not gid:
            await update.message.reply_text(
                "Set TELEGRAM_MAIN_GROUP_ID in .env for Members Results."
            )
            return

    try:
        topic = await context.bot.create_forum_topic(chat_id=gid, name=name)
    except Exception as e:
        await update.message.reply_text(
            f"Could not create topic: {e}\n\n"
            "Bot must be group admin with Manage Topics permission."
        )
        return

    thread_id = topic.message_thread_id
    await update.message.reply_text(
        f"✅ Created forum topic <b>{name}</b>\n\n"
        f"Set in Railway:\n"
        f"<code>{env_key}={thread_id}</code>\n\n"
        "Then redeploy the bot.",
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
    for key in ("members", "finance", "checklist"):
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
    if not report.get("all_ok"):
        lines.append("")
        lines.append(
            "Fix automatically: `/airtable_setup` \\(needs token scope "
            "`schema.bases:write`\\)"
        )
    if report.get("all_ok"):
        lines.append("")
        lines.append(
            "*How to test member sync:*\n"
            "1. Claim Whop → check *Members* row (Status Active, Plan filled)\n"
            "2. Complete onboarding contact → Email, Phone, Platform, Platform User ID\n"
            "3. Admin approve screenshot → Status stays Active\n"
            "4. Log expense: `/expense 10 USD Ads test` → *Finance* row Type Expense\n"
            "5. Whop payment webhook → *Finance* row Type Payment\n"
            "6. P&amp;L: `/pnl 30`"
        )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ---------- /airtable_setup ----------

@admin_only
@log_call
async def cmd_airtable_setup(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Create missing Airtable tables/columns (one-click schema sync)."""
    import asyncio

    from airtable.schema_migrate import migrate_airtable_schema

    await update.message.reply_text(
        "Syncing Airtable schema… this may take a minute."
    )

    report = await asyncio.to_thread(
        migrate_airtable_schema, create_missing_tables=True
    )

    if report.get("reason"):
        await update.message.reply_text(f"❌ {report['reason']}")
        return

    lines = ["<b>Airtable Schema Setup</b>", ""]
    if report.get("deprecated_table"):
        lines.append(f"✅ <code>{html.escape(str(report['deprecated_table']))}</code>")
        lines.append("")
    for table_name, info in report.get("tables", {}).items():
        errors = info.get("errors") or []
        error = info.get("error")
        added = info.get("added") or []
        fixed = info.get("fixed") or []
        if info.get("created"):
            icon = "✅"
            detail = f"created table ({len(added)} fields)"
        elif errors or error:
            icon = "❌"
            detail = error or "; ".join(errors[:3])
        elif added or fixed:
            icon = "✅"
            parts = []
            if added:
                parts.append(f"added: {', '.join(added)}")
            if fixed:
                parts.append(f"fixed: {', '.join(fixed)}")
            detail = "; ".join(parts)
        else:
            icon = "✅"
            detail = "already up to date"
        safe_table = html.escape(str(table_name))
        safe_detail = html.escape(str(detail))
        lines.append(f"{icon} <b>{safe_table}</b> — {safe_detail}")

    overall = "✅ Done" if report.get("ok") else "⚠️ Some fields failed"
    lines.extend(
        ["", f"<b>Overall:</b> {overall}", "", "Run /airtable_check to verify."]
    )
    body = "\n".join(lines)
    try:
        await update.message.reply_text(body, parse_mode=ParseMode.HTML)
    except Exception:
        plain = ["Airtable Schema Setup", ""]
        if report.get("deprecated_table"):
            plain.append(str(report["deprecated_table"]))
        for table_name, info in report.get("tables", {}).items():
            row = [str(table_name)]
            if info.get("added"):
                row.append(f"added: {', '.join(info['added'])}")
            if info.get("fixed"):
                row.append(f"fixed: {', '.join(info['fixed'])}")
            if info.get("errors"):
                row.append(f"errors: {'; '.join(info['errors'][:3])}")
            if info.get("error"):
                row.append(str(info["error"]))
            if len(row) == 1:
                row.append("ok")
            plain.append(" — ".join(row))
        plain.extend(["", f"Overall: {overall}"])
        await update.message.reply_text("\n".join(plain))


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
    airtable_synced = 0
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

        plan = plan_mapping.resolve_plan_from_membership(m)
        if plan == "unknown" and product_id:
            try:
                product = await client.get_product(str(product_id))
                plan = plan_mapping.resolve_plan_name(
                    product_id,
                    (product.get("title") or product.get("name")),
                )
            except WhopAPIError:
                pass

        profile = profile_from_membership(m)
        existing_tg = storage.get_telegram_id_for_whop_user(whop_user)
        tg_username: str | None = None
        tg_name: str | None = profile.name
        local_platform: str | None = None
        local_platform_uid: str | None = None
        local_phone: str | None = profile.phone
        if existing_tg:
            local = storage.get_user(existing_tg) or {}
            tg_username = local.get("username") or None
            tg_name = airtable_sync._name_from_user(local) or profile.name
            local_platform = local.get("platform")
            local_platform_uid = local.get("platform_user_id")
            if local.get("contact_phone"):
                local_phone = local.get("contact_phone")
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

        email = profile.email
        if existing_tg:
            local = storage.get_user(existing_tg) or {}
            email = (
                airtable_sync._email_from_user(local, profile.email)
                or profile.email
            )

        await airtable_sync.sync_whop_membership(
            whop_user_id=str(whop_user),
            whop_membership_id=m.get("id"),
            plan=plan,
            email=email,
            name=tg_name,
            phone=local_phone,
            join_date=profile.join_date,
            telegram_user_id=existing_tg,
            telegram_username=tg_username,
            telegram_claimed=existing_tg is not None,
            platform=local_platform,
            platform_user_id=local_platform_uid,
        )
        airtable_synced += 1

    dedupe = await airtable_sync.reconcile_members_table()
    client_links = await airtable_sync.link_all_platform_clients()

    body = (
        "🔄 *Sync complete*\n\n"
        f"• Memberships fetched: *{fetched}*\n"
        f"• Already linked + refreshed: *{linked}*\n"
        f"• Awaiting `/claim` link: *{pending}*\n"
        f"• Airtable rows upserted: *{airtable_synced}*\n"
        f"• Duplicate groups merged: *{dedupe.get('groups_merged', 0)}* "
        f"(`{dedupe.get('rows_before', 0)}` → `{dedupe.get('rows_after', 0)}` rows)\n"
        f"• Platform client links: *{client_links.get('linked', 0)}* linked, "
        f"*{client_links.get('missing_client', 0)}* UID not in client table"
    )
    await update.message.reply_text(body, parse_mode=ParseMode.MARKDOWN)


@admin_only
@log_call
async def cmd_fix_members_crm(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Backfill member CRM fields from bot storage + link Vantage/Premier clients."""
    await update.message.reply_text(
        "Backfilling member CRM from bot storage and linking platform clients…"
    )
    dedupe = await airtable_sync.reconcile_members_table()
    members = await airtable_sync.backfill_members_crm_from_storage()
    links = await airtable_sync.link_all_platform_clients()
    await update.message.reply_text(
        "✅ *Members CRM backfill complete*\n\n"
        f"• Rows updated from bot storage: *{members.get('updated', 0)}*\n"
        f"• Client links from storage: *{members.get('linked_clients', 0)}*\n"
        f"• Skipped (no data): *{members.get('skipped', 0)}*\n"
        f"• Failed: *{members.get('failed', 0)}*\n"
        f"• Duplicate groups merged: *{dedupe.get('groups_merged', 0)}*\n"
        f"• All-member client scan: *{links.get('linked', 0)}* linked, "
        f"*{links.get('missing_client', 0)}* no matching UID",
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
@log_call
async def cmd_fix_onboarding_crm(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Backfill Onboarding Completed checkbox for all locally approved users."""
    await update.message.reply_text(
        "Syncing Onboarding Completed checkboxes to Airtable…"
    )
    dedupe = await airtable_sync.reconcile_members_table()
    result = await airtable_sync.backfill_onboarding_completed_in_crm()
    await update.message.reply_text(
        "✅ *Onboarding CRM backfill complete*\n\n"
        f"• Checkboxes updated: *{result.get('ok', 0)}*\n"
        f"• Failed: *{result.get('failed', 0)}*\n"
        f"• Duplicate groups merged: *{dedupe.get('groups_merged', 0)}*",
        parse_mode=ParseMode.MARKDOWN,
    )
