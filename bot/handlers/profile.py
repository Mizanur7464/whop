"""/profile — show the caller's membership info."""

from __future__ import annotations

from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot import keyboards, storage, texts
from bot.access import idle_after_complete_message, shows_main_menu
from bot.channel_context import ensure_private_dm
from bot.community_layout import FLOW_WELCOME
from bot.decorators import log_call


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %b %Y")
    except Exception:
        return iso


@log_call
async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_private_dm(
        update, context, flow=FLOW_WELCOME, command="profile"
    ):
        return

    user = update.effective_user
    if not shows_main_menu(user.id):
        await update.message.reply_text(idle_after_complete_message())
        return

    record = storage.get_user(user.id)

    if not record:
        await update.message.reply_text(
            texts.PROFILE_NOT_FOUND,
            reply_markup=keyboards.back_only(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    name_parts = [record.get("first_name", ""), record.get("last_name", "")]
    name = " ".join(p for p in name_parts if p) or (user.username or "—")

    body = texts.PROFILE_TEMPLATE.format(
        name=name,
        user_id=record["user_id"],
        plan=record.get("plan", "unknown").title(),
        joined=_fmt_date(record.get("joined_at")),
        status=record.get("status", "active").title(),
    )

    await update.message.reply_text(
        body,
        reply_markup=keyboards.back_only(),
        parse_mode=ParseMode.MARKDOWN,
    )
