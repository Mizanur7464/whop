"""
Copy trading channel flow (buyer doc).

Welcome -> Set up -> Platform (Vantage/Premier) -> PDF -> Checklist ->
Warning -> Everything is set up -> Success message.

Callbacks: ``ct:*`` (e.g. ``ct:setup``, ``ct:plat:vantage``, ``ct:chk:doc_followed``).
"""

from __future__ import annotations

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from airtable import sync as airtable_sync
from bot import copy_trading_config, keyboards, storage
from bot.copy_trading_config import platform_by_id
from bot.decorators import log_call
from bot.channel_context import block_if_group_chat, ensure_copytrading_channel
from bot.community_layout import FLOW_COPYTRADING
from bot.messaging import send_document, send_text
from bot.telegram_utils import safe_answer_callback


def _ct_action(data: str) -> str:
    return data[3:] if data.startswith("ct:") else ""


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
    await send_text(update, context, text, markup=markup, flow=FLOW_COPYTRADING)


def _progress_bar(done: int, total: int, width: int = 10) -> str:
    if total == 0:
        return ""
    filled = round(width * done / total)
    return "▰" * filled + "▱" * (width - filled)


def _all_done(user_id: int) -> bool:
    cfg = copy_trading_config.get()
    done_map = storage.get_copytrading_checklist(user_id)
    return all(done_map.get(item.id) for item in cfg.checklist_items)


async def show_welcome(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = copy_trading_config.get()
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(cfg.btn_setup, callback_data="ct:setup")]]
    )
    await _send_or_edit(update, cfg.welcome_message, markup)


async def show_platforms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = copy_trading_config.get()
    rows = [
        [InlineKeyboardButton(p.label, callback_data=f"ct:plat:{p.id}")]
        for p in cfg.platforms
    ]
    if not rows:
        await _send_or_edit(
            update, "Platform options are not configured yet.", None
        )
        return
    await _send_new_message(update, context, cfg.platform_prompt, InlineKeyboardMarkup(rows))


async def _send_platform_doc(
    update: Update, context: ContextTypes.DEFAULT_TYPE, platform_id: str
) -> None:
    plat = platform_by_id(platform_id)
    if not plat:
        await update.callback_query.answer("Invalid selection.", show_alert=True)
        return

    user = update.effective_user
    storage.upsert_user(user.id, copytrading_platform=plat.label)

    if plat.doc.type == "url" and plat.doc.url:
        await send_text(
            update,
            context,
            f"{plat.doc.caption}\n\n{plat.doc.url}",
            flow=FLOW_COPYTRADING,
            disable_preview=False,
        )
    elif plat.doc.type == "file" and plat.doc.path:
        try:
            with open(plat.doc.path, "rb") as f:
                await send_document(
                    update,
                    context,
                    f,
                    caption=plat.doc.caption or f"{plat.label} copy trading guide",
                    flow=FLOW_COPYTRADING,
                )
        except FileNotFoundError:
            await send_text(
                update,
                context,
                "Copy trading document is not uploaded yet. The team will add it shortly.",
                flow=FLOW_COPYTRADING,
            )

    await update.callback_query.answer("Document sent ✅")


async def show_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = copy_trading_config.get()
    user = update.effective_user
    done_map = storage.get_copytrading_checklist(user.id)
    items = [
        {"id": item.id, "title": item.title, "done": done_map.get(item.id, False)}
        for item in cfg.checklist_items
    ]
    done = sum(1 for it in items if it["done"])
    total = len(items)
    text = f"{cfg.checklist_intro}\n\nProgress: {done}/{total}  {_progress_bar(done, total)}"
    markup = keyboards.copytrading_checklist_keyboard(
        items, continue_label=cfg.btn_continue
    )

    if update.callback_query and update.callback_query.data.startswith("ct:plat:"):
        await send_text(update, context, text, markup=markup, flow=FLOW_COPYTRADING)
    else:
        await _send_or_edit(update, text, markup)


async def show_warning(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _all_done(user.id):
        await update.callback_query.answer(
            "Please complete all checklist steps first.", show_alert=True
        )
        return
    cfg = copy_trading_config.get()
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    cfg.btn_everything_set_up, callback_data="ct:confirm"
                )
            ]
        ]
    )
    await _send_or_edit(update, cfg.confirmation_warning_message, markup)


async def show_success(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _all_done(user.id):
        await update.callback_query.answer(
            "Please complete all checklist steps first.", show_alert=True
        )
        return

    cfg = copy_trading_config.get()
    storage.mark_copytrading_completed(user.id)
    u = storage.get_user(user.id) or {}
    await airtable_sync.copytrading_completed(
        user.id,
        platform=u.get("copytrading_platform"),
        telegram_username=user.username,
        name=user.full_name,
    )
    await _send_or_edit(update, cfg.success_message, None)
    await update.callback_query.answer("Copy trading setup complete ✅")


@log_call
async def on_copytrading_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if await block_if_group_chat(
        update, context, flow=FLOW_COPYTRADING, command="copytrading"
    ):
        return

    query = update.callback_query
    await safe_answer_callback(query)
    action = _ct_action(query.data or "" if query else "")
    logger.info(f"copy trading callback: {query.data!r}" if query else "copy trading callback")

    if action == "setup":
        await show_platforms(update, context)
    elif action.startswith("plat:"):
        platform_id = action.split(":", 1)[1]
        await _send_platform_doc(update, context, platform_id)
        await show_checklist(update, context)
    elif action.startswith("chk:"):
        item_id = action.split(":", 1)[1]
        user = update.effective_user
        new_state = storage.toggle_copytrading_checklist_item(user.id, item_id)
        cfg = copy_trading_config.get()
        item_title = next(
            (item.title for item in cfg.checklist_items if item.id == item_id),
            item_id,
        )
        await airtable_sync.copytrading_checklist_toggled(
            telegram_user_id=user.id,
            task_id=item_id,
            task_title=item_title,
            completed=new_state,
        )
        await show_checklist(update, context)
    elif action == "continue":
        await show_warning(update, context)
    elif action == "confirm":
        await show_success(update, context)
    else:
        logger.warning(f"Unknown copy trading action: {action}")


@log_call
async def cmd_copytrading(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/copytrading`` — start or restart the copy trading setup flow."""
    if not await ensure_copytrading_channel(update, context):
        return

    user = update.effective_user
    storage.reset_copytrading_flow(user.id)
    await show_welcome(update, context)
