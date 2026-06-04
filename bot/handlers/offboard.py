"""
Offboard channel flow (buyer doc).

Welcome -> Offboard -> Platform -> PDF -> Continue ->
7-question form -> Submit -> Email + confirmation.

Callbacks: ``ob:*``  Form text: ``context.user_data["offboard_form"]``
"""

from __future__ import annotations

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot import offboard_config
from bot.offboard_config import platform_by_id
from bot.decorators import log_call
from bot.channel_context import ensure_offboard_channel
from bot.community_layout import FLOW_OFFBOARD
from bot.messaging import send_document, send_text
from bot.telegram_utils import safe_answer_callback
from config import settings
from integrations import email_ops


FORM_KEY = "offboard_form"


def _ob_action(data: str) -> str:
    return data[3:] if data.startswith("ob:") else ""


def _get_form(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    return context.user_data.get(FORM_KEY)


def _clear_form(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(FORM_KEY, None)


def _start_form(context: ContextTypes.DEFAULT_TYPE, platform: str) -> None:
    cfg = offboard_config.get()
    context.user_data[FORM_KEY] = {
        "step_index": 0,
        "platform": platform,
        "answers": {},
    }
    return cfg.form_questions[0].prompt if cfg.form_questions else None


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


async def _send_new_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    await send_text(update, context, text, markup=markup, flow=FLOW_OFFBOARD)


async def show_welcome(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = offboard_config.get()
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(cfg.btn_offboard, callback_data="ob:start")]]
    )
    await _send_or_edit(update, cfg.welcome_message, markup)


async def show_platforms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = offboard_config.get()
    _clear_form(context)
    rows = [
        [InlineKeyboardButton(p.label, callback_data=f"ob:plat:{p.id}")]
        for p in cfg.platforms
    ]
    await _send_new_message(update, context, cfg.platform_prompt, InlineKeyboardMarkup(rows))


async def _send_platform_doc(
    update: Update, context: ContextTypes.DEFAULT_TYPE, platform_id: str
) -> None:
    plat = platform_by_id(platform_id)
    if not plat:
        await update.callback_query.answer("Invalid selection.", show_alert=True)
        return

    user = update.effective_user
    context.user_data["offboard_platform"] = plat.label

    if plat.doc.type == "file" and plat.doc.path:
        try:
            with open(plat.doc.path, "rb") as f:
                await send_document(
                    update,
                    context,
                    f,
                    caption=plat.doc.caption or f"{plat.label} offboard guide",
                    flow=FLOW_OFFBOARD,
                )
        except FileNotFoundError:
            await send_text(
                update,
                context,
                "Offboard document is not uploaded yet. The team will add it shortly.",
                flow=FLOW_OFFBOARD,
            )

    cfg = offboard_config.get()
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(cfg.btn_continue, callback_data="ob:form")]]
    )
    await send_text(update, context, cfg.after_doc_message, markup=markup, flow=FLOW_OFFBOARD)
    await update.callback_query.answer("Document sent ✅")


async def _show_submit_screen(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    form = _get_form(context)
    if not form:
        return
    cfg = offboard_config.get()
    answers = form["answers"]
    lines = [f"• {q.id.replace('_', ' ').title()}: {answers.get(q.id, '—')}" for q in cfg.form_questions]
    lines.insert(0, f"• Platform: {form.get('platform', '—')}")
    summary = "Please review your answers:\n\n" + "\n".join(lines)
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(cfg.btn_submit, callback_data="ob:submit"),
                InlineKeyboardButton("Cancel", callback_data="ob:cancel"),
            ]
        ]
    )
    await update.effective_message.reply_text(summary, reply_markup=markup)


async def _start_form_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    platform = context.user_data.get("offboard_platform", "—")
    cfg = offboard_config.get()
    _start_form(context, platform)
    await update.callback_query.answer()
    await send_text(update, context, cfg.form_intro, flow=FLOW_OFFBOARD)
    if cfg.form_questions:
        await send_text(
            update, context, cfg.form_questions[0].prompt, flow=FLOW_OFFBOARD
        )


@log_call
async def on_form_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Collect form answers when user is in offboard form mode."""
    form = _get_form(context)
    if not form or update.message is None:
        return

    cfg = offboard_config.get()
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

    next_q = cfg.form_questions[form["step_index"]]
    await update.message.reply_text(next_q.prompt)


async def _submit_form(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    form = _get_form(context)
    if not form:
        await update.callback_query.answer("No form in progress.", show_alert=True)
        return

    user = update.effective_user
    cfg = offboard_config.get()
    answers = form["answers"]
    platform = form.get("platform", context.user_data.get("offboard_platform", "—"))

    body_lines = [
        f"Form type: Offboard request",
        f"Telegram user ID: {user.id}",
        f"Telegram name: {user.first_name or ''} {user.last_name or ''}".strip(),
        f"Platform: {platform}",
        "",
    ]
    for q in cfg.form_questions:
        body_lines.append(f"{q.id}: {answers.get(q.id, '—')}")

    body = "\n".join(body_lines)
    subject = f"[Fusion Wealth] Offboard request — {answers.get('first_name', '')} {answers.get('last_name', '')}".strip()

    sent = email_ops.send_form_email(
        subject=subject,
        body=body,
        form_type="offboard",
        telegram_user_id=user.id,
    )

    # Notify admins if email failed
    if not sent:
        for admin_id in settings.telegram_admin_ids:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"📋 *Offboard submission* (email not sent — check SMTP)\n\n```\n{body[:3500]}\n```",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                logger.warning(f"Could not notify admin {admin_id}: {e}")

    _clear_form(context)
    context.user_data.pop("offboard_platform", None)

    await update.callback_query.answer("Submitted ✅")
    try:
        await update.callback_query.edit_message_text(cfg.submitted_message)
    except BadRequest:
        await context.bot.send_message(
            chat_id=user.id, text=cfg.submitted_message
        )


@log_call
async def on_offboard_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await safe_answer_callback(query)
    action = _ob_action(query.data or "" if query else "")
    logger.info(f"offboard callback: {query.data!r}" if query else "offboard callback")

    if action == "start":
        await show_platforms(update, context)
    elif action.startswith("plat:"):
        await _send_platform_doc(update, context, action.split(":", 1)[1])
    elif action == "form":
        await _start_form_flow(update, context)
    elif action == "submit":
        await _submit_form(update, context)
    elif action == "cancel":
        _clear_form(context)
        await update.callback_query.edit_message_text(
            "Offboard request cancelled. Send /offboard to start again."
        )
    else:
        logger.warning(f"Unknown offboard action: {action}")


def offboard_form_active(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(_get_form(context))


@log_call
async def cmd_offboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/offboard`` — start the opt-out flow."""
    if not await ensure_offboard_channel(update, context):
        return

    _clear_form(context)
    context.user_data.pop("offboard_platform", None)
    await show_welcome(update, context)
