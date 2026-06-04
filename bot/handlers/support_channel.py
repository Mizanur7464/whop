"""
Support channel flow (buyer doc).

Welcome -> Continue -> 7-question form -> Submit -> Email + confirmation.

Callbacks: ``sp:*``  Form text: ``context.user_data["support_form"]``
"""

from __future__ import annotations

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from airtable import sync as airtable_sync
from bot import support_form_config
from bot.decorators import log_call
from bot.channel_context import block_if_group_chat, ensure_support_channel
from bot.community_layout import FLOW_SUPPORT
from bot.messaging import send_text
from bot.telegram_utils import safe_answer_callback
from config import settings
from integrations import email_ops

FORM_KEY = "support_form"


def _sp_action(data: str) -> str:
    return data[3:] if data.startswith("sp:") else ""


def _get_form(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    return context.user_data.get(FORM_KEY)


def _clear_form(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(FORM_KEY, None)


def _start_form(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[FORM_KEY] = {"step_index": 0, "answers": {}}


def support_form_active(_: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(_get_form(context))


async def _send_or_edit(
    update: Update, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    kwargs = dict(parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=markup, **kwargs
            )
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return
            await update.callback_query.message.reply_text(
                text, reply_markup=markup, **kwargs
            )
    else:
        await update.effective_message.reply_text(text, reply_markup=markup, **kwargs)


async def show_welcome(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = support_form_config.get()
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(cfg.btn_continue, callback_data="sp:form")]]
    )
    await _send_or_edit(update, cfg.welcome_message, markup)


async def _show_submit_screen(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    form = _get_form(context)
    if not form:
        return
    cfg = support_form_config.get()
    answers = form["answers"]
    lines = [
        f"• {q.id.replace('_', ' ').title()}: {answers.get(q.id, '—')}"
        for q in cfg.form_questions
    ]
    summary = "Please review your answers:\n\n" + "\n".join(lines)
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(cfg.btn_submit, callback_data="sp:submit"),
                InlineKeyboardButton("Cancel", callback_data="sp:cancel"),
            ]
        ]
    )
    await update.effective_message.reply_text(summary, reply_markup=markup)


async def _start_form_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = support_form_config.get()
    _start_form(context)
    await update.callback_query.answer()
    await send_text(update, context, cfg.form_intro, flow=FLOW_SUPPORT)
    if cfg.form_questions:
        await send_text(
            update, context, cfg.form_questions[0].prompt, flow=FLOW_SUPPORT
        )


@log_call
async def on_form_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    form = _get_form(context)
    if not form or update.message is None:
        return

    cfg = support_form_config.get()
    idx = form["step_index"]
    if idx >= len(cfg.form_questions):
        return

    q = cfg.form_questions[idx]
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Please send a valid answer.")
        return

    if q.id == "telegram_username" and not text.startswith("@"):
        text = f"@{text.lstrip('@')}"

    form["answers"][q.id] = text
    form["step_index"] = idx + 1

    if form["step_index"] >= len(cfg.form_questions):
        await _show_submit_screen(update, context)
        return

    await update.message.reply_text(cfg.form_questions[form["step_index"]].prompt)


async def _submit_form(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    form = _get_form(context)
    if not form:
        await update.callback_query.answer("No form in progress.", show_alert=True)
        return

    user = update.effective_user
    cfg = support_form_config.get()
    answers = form["answers"]

    body_lines = [
        "Form type: Support request",
        f"Telegram user ID: {user.id}",
        f"Telegram name: {user.first_name or ''} {user.last_name or ''}".strip(),
        "",
    ]
    for q in cfg.form_questions:
        body_lines.append(f"{q.id}: {answers.get(q.id, '—')}")

    body = "\n".join(body_lines)
    subject = (
        f"[Fusion Wealth] Support request — "
        f"{answers.get('first_name', '')} {answers.get('last_name', '')}".strip()
    )

    sent = email_ops.send_form_email(
        subject=subject,
        body=body,
        form_type="support",
        telegram_user_id=user.id,
    )

    summary = "\n".join(
        f"{q.id}: {answers.get(q.id, '—')}" for q in cfg.form_questions
    )
    await airtable_sync.support_submitted(
        telegram_user_id=user.id,
        telegram_username=user.username,
        name=user.full_name,
        summary=summary,
    )

    if not sent:
        for admin_id in settings.telegram_admin_ids:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "📋 *Support submission* (email not sent — check SMTP)\n\n"
                        f"```\n{body[:3500]}\n```"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                logger.warning(f"Could not notify admin {admin_id}: {e}")

    _clear_form(context)
    await update.callback_query.answer("Submitted ✅")
    try:
        await update.callback_query.edit_message_text(cfg.submitted_message)
    except BadRequest:
        await context.bot.send_message(
            chat_id=user.id, text=cfg.submitted_message
        )


@log_call
async def on_support_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if await block_if_group_chat(
        update, context, flow=FLOW_SUPPORT, command="support"
    ):
        return

    query = update.callback_query
    await safe_answer_callback(query)
    action = _sp_action(query.data or "" if query else "")
    logger.info(f"support callback: {update.callback_query.data!r}")

    if action == "form":
        await _start_form_flow(update, context)
    elif action == "submit":
        await _submit_form(update, context)
    elif action == "cancel":
        _clear_form(context)
        await update.callback_query.edit_message_text(
            "Support request cancelled. Send /support to start again."
        )
    else:
        logger.warning(f"Unknown support action: {action}")


@log_call
async def cmd_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/support`` — start the support contact form (buyer doc)."""
    if not await ensure_support_channel(update, context):
        return

    _clear_form(context)
    await show_welcome(update, context)
