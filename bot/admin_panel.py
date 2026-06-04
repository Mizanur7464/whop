"""
Admin control panel — /admin and inline navigation.

Shows all admin commands and features in one place (Menu + callback buttons).
Uses HTML parse mode (underscores in env var names break legacy Markdown).
"""

from __future__ import annotations

import html as html_lib

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot import storage, texts
from bot.decorators import is_admin
from bot.telegram_utils import safe_answer_callback
from config import settings

_PARSE = ParseMode.HTML


def _e(value: object) -> str:
    return html_lib.escape(str(value))


def _panel_home_text() -> str:
    safe = "ON" if settings.safe_mode else "OFF"
    layout = (settings.telegram_community_layout or "topics").strip()
    return (
        "🔐 <b>Admin Control Panel</b>\n\n"
        "All tools for running Fusion Wealth. Tap a section below "
        "or use any command from the Menu (/).\n\n"
        f"• Environment: <code>{_e(settings.environment)}</code>\n"
        f"• Layout: <code>{_e(layout)}</code>\n"
        f"• SAFE_MODE: <code>{safe}</code> "
        "<i>(invites blocked when ON)</i>\n\n"
        "<b>Quick overview</b>\n"
        "👥 Moderation — stats, ban, broadcast\n"
        "💳 Whop — claim, sync, API test\n"
        "🏘 Community — topics, onboarding flows\n"
        "💰 Finance — Airtable P&amp;L\n"
        "⚙️ System — config reload, build status"
    )


_SECTIONS: dict[str, str] = {
    "moderation": (
        "👥 <b>Members &amp; moderation</b>\n\n"
        "<code>/stats</code> — Live member counts\n"
        "<code>/broadcast &lt;message&gt;</code> — Message all active members "
        "(confirm with buttons)\n"
        "<code>/ban &lt;telegram_user_id&gt;</code> — Ban in bot storage\n"
        "<code>/unban &lt;telegram_user_id&gt;</code> — Reinstate user\n\n"
        "<i>Screenshot review:</i> approve/reject buttons in your DM "
        "when a member submits onboarding proof."
    ),
    "whop": (
        "💳 <b>Whop &amp; access</b>\n\n"
        "<code>/claim &lt;code&gt;</code> — Member links Whop purchase to Telegram\n"
        "<code>/claims</code> — List pending claim codes\n"
        "<code>/sync</code> — Pull valid memberships from Whop API\n"
        "<code>/whop_test</code> — Ping Whop API key\n\n"
        "<i>Production:</i> Whop webhook → auto claim codes. "
        "Set <code>WHOP_*</code> and deploy <code>PUBLIC_WEBHOOK_URL</code> first."
    ),
    "community": (
        "🏘 <b>Community flows</b>\n\n"
        "<b>Member flows — private DM only</b> (group topics = guides + Open bot):\n"
        "<code>/start</code> <code>/onboarding</code> — Welcome + T&amp;C + screenshot\n"
        "<code>/copytrading</code> — Copy trading setup\n"
        "<code>/support</code> — Support form\n"
        "<code>/help</code> — Member help\n\n"
        "<b>Setup:</b>\n"
        "<code>/topicid</code> — Run inside each forum topic → copy IDs to "
        "<code>.env</code>\n"
        "<code>/reload_config</code> — Hot-reload JSON flows\n\n"
        "<i>Admins can run flow commands in private chat for testing.</i>"
    ),
    "finance": (
        "💰 <b>Finance (Airtable)</b>\n\n"
        "<code>/expense &lt;amount&gt; &lt;currency&gt; &lt;category&gt; "
        "&lt;description&gt;</code>\n"
        "Example: <code>/expense 75 USD Ads Facebook May</code>\n\n"
        "<code>/revenue [days]</code> — Revenue summary (default 30 days)\n"
        "<code>/expenses [days]</code> — Expense summary\n"
        "<code>/pnl [days]</code> — Profit &amp; loss\n"
        "<code>/airtable_check</code> — Validate base tables &amp; fields\n\n"
        "Requires <code>AIRTABLE_API_KEY</code>, <code>AIRTABLE_BASE_ID</code>, "
        "and <code>pyairtable</code>."
    ),
    "system": (
        "⚙️ <b>System &amp; diagnostics</b>\n\n"
        "<code>/admin</code> — This panel\n"
        "<code>/status</code> — Build / phase status\n"
        "<code>/reload_config</code> — Reload onboarding &amp; layout JSON\n"
        "<code>/profile</code> <code>/checklist</code> — Test member views\n\n"
        "<b>Env highlights:</b>\n"
        "• <code>TELEGRAM_MAIN_GROUP_ID</code> + <code>TELEGRAM_TOPIC_*</code>\n"
        "• <code>TELEGRAM_ADMIN_IDS</code> / "
        "<code>TELEGRAM_REVIEW_ADMIN_IDS</code>\n"
        "• <code>SAFE_MODE</code> — disable for real invite links"
    ),
}


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👥 Members", callback_data="admin:section:moderation"),
                InlineKeyboardButton("💳 Whop", callback_data="admin:section:whop"),
            ],
            [
                InlineKeyboardButton("🏘 Community", callback_data="admin:section:community"),
                InlineKeyboardButton("💰 Finance", callback_data="admin:section:finance"),
            ],
            [
                InlineKeyboardButton("⚙️ System", callback_data="admin:section:system"),
                InlineKeyboardButton("📊 Live stats", callback_data="admin:stats"),
            ],
            [
                InlineKeyboardButton("✖️ Close", callback_data="admin:close"),
            ],
        ]
    )


def admin_section_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⬅️ Back to panel", callback_data="admin:home")],
            [InlineKeyboardButton("✖️ Close", callback_data="admin:close")],
        ]
    )


async def _send(
    update: Update,
    text: str,
    markup: InlineKeyboardMarkup | None,
    *,
    edit: bool,
) -> None:
    kwargs = {
        "text": text,
        "reply_markup": markup,
        "parse_mode": _PARSE,
        "disable_web_page_preview": True,
    }
    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(**kwargs)
            return
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return
            raise
    msg = update.effective_message
    if msg:
        await msg.reply_text(**kwargs)


async def show_admin_panel(
    update: Update,
    _: ContextTypes.DEFAULT_TYPE,
    *,
    edit: bool = False,
) -> None:
    await _send(update, _panel_home_text(), admin_panel_keyboard(), edit=edit)


def _stats_text_html() -> str:
    s = storage.stats()
    return (
        "📊 <b>Live Stats</b>\n\n"
        f"• Total members: <b>{s['total']}</b>\n"
        f"• Active: <b>{s['active']}</b>\n"
        f"• Banned: <b>{s['banned']}</b>\n"
        f"• New today: <b>{s['new_today']}</b>\n"
        f"• Phase: <b>Production</b>"
    )


async def on_admin_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await safe_answer_callback(query)
    user = update.effective_user
    if not user or not is_admin(user.id):
        await query.answer(texts.UNAUTHORIZED, show_alert=True)
        return

    data = query.data or ""
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "home"

    if action == "home":
        await show_admin_panel(update, context, edit=True)
    elif action == "section" and len(parts) > 2:
        key = parts[2]
        body = _SECTIONS.get(key, _panel_home_text())
        await _send(update, body, admin_section_keyboard(), edit=True)
    elif action == "stats":
        await _send(
            update,
            _stats_text_html() + "\n\n<i>Tap Back to return to the admin panel.</i>",
            admin_section_keyboard(),
            edit=True,
        )
    elif action == "close":
        try:
            await query.delete_message()
        except BadRequest:
            pass
