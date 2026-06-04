"""DM members who leave the main group and ask why (buyer feedback)."""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from telegram import ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.ext import ContextTypes

from airtable import sync as airtable_sync
from bot.leave_survey_config import get as leave_cfg
from config import settings

_LEAVE_REASON_KEY = "leave_survey_reason"


def leave_reason_active(_: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.user_data.get(_LEAVE_REASON_KEY))


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cm: ChatMemberUpdated | None = update.chat_member
    if not cm or not settings.telegram_main_group_id:
        return
    if cm.chat.id != settings.telegram_main_group_id:
        return

    old = cm.old_chat_member.status
    new = cm.new_chat_member.status
    if new != ChatMemberStatus.LEFT:
        return
    if old not in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
        ChatMemberStatus.ADMINISTRATOR,
    ):
        return

    user = cm.new_chat_member.user
    if not user or user.is_bot:
        return

    cfg = leave_cfg()
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    cfg.btn_submit_reason, callback_data="lv:submit"
                )
            ]
        ]
    )
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=cfg.dm_message,
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.info(f"leave_survey: could not DM user {user.id}: {e}")


async def on_leave_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query or not query.data or query.data != "lv:submit":
        return
    await query.answer()

    user = update.effective_user
    if not user:
        return

    cfg = leave_cfg()
    context.user_data[_LEAVE_REASON_KEY] = True
    await query.edit_message_text(cfg.reason_prompt)


async def on_leave_reason_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not context.user_data.pop(_LEAVE_REASON_KEY, None):
        return
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return

    cfg = leave_cfg()
    reason = update.message.text.strip()[:500]
    if not reason:
        context.user_data[_LEAVE_REASON_KEY] = True
        await update.message.reply_text(cfg.reason_prompt)
        return

    when = datetime.now(timezone.utc).isoformat()
    await airtable_sync.member_left_group(
        telegram_user_id=user.id,
        telegram_username=user.username,
        name=user.full_name,
        reason=reason,
        left_at_iso=when,
    )
    await update.message.reply_text(cfg.thanks_message)
