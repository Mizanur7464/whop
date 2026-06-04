"""
Central callback-query router.

All inline-button clicks come here first. Based on the callback_data
prefix we dispatch to the right action. This keeps `add_handler` calls
in main.py minimal.

Convention: "<feature>:<action>[:<param>]"
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from airtable import sync as airtable_sync
from bot import keyboards, onboarding_config, storage, texts
from bot.access import idle_after_complete_message, shows_main_menu
from bot.decorators import is_admin
from bot.admin_panel import show_admin_panel
from bot.handlers import onboarding as onboarding_handlers
from bot.telegram_utils import safe_answer_callback


async def _edit(update: Update, body: str, markup=None) -> None:
    """Safely edit the previous message; ignore 'message not modified'."""
    query = update.callback_query
    try:
        await query.edit_message_text(
            body,
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %b %Y")
    except Exception:
        return iso


def _progress_bar(done: int, total: int, width: int = 10) -> str:
    if total == 0:
        return ""
    filled = round(width * done / total)
    return "▰" * filled + "▱" * (width - filled)


# ---------- main router ----------

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_answer_callback(query)

    data = query.data or ""
    if data.startswith(("onb:", "ct:", "ob:", "sp:")):
        return

    user = update.effective_user
    logger.debug(f"callback: {data} from {user.id}")

    if not shows_main_menu(user.id):
        await _edit(update, idle_after_complete_message(), markup=None)
        return

    parts = data.split(":")
    feature = parts[0] if parts else ""

    if feature == "menu":
        await _handle_menu(update, context, parts[1:])
    elif feature == "checklist":
        await _handle_checklist(update, context, parts[1:])
    elif feature == "broadcast":
        await _handle_broadcast(update, context, parts[1:])
    else:
        logger.warning(f"Unknown callback: {data}")


# ---------- menu actions ----------

async def _handle_menu(update: Update, context, args: list[str]) -> None:
    action = args[0] if args else "home"
    user = update.effective_user

    if action == "home":
        if onboarding_handlers.needs_onboarding(user.id):
            await onboarding_handlers.show_welcome(update, context)
            return
        await _edit(
            update,
            texts.WELCOME_RETURNING.format(first_name=user.first_name or "there"),
            keyboards.main_menu(is_admin=is_admin(user.id)),
        )

    elif action == "profile":
        record = storage.get_user(user.id)
        if not record:
            await _edit(update, texts.PROFILE_NOT_FOUND, keyboards.back_only())
            return
        name = " ".join(
            p for p in [record.get("first_name", ""), record.get("last_name", "")] if p
        ) or (user.username or "—")
        body = texts.PROFILE_TEMPLATE.format(
            name=name,
            user_id=record["user_id"],
            plan=record.get("plan", "unknown").title(),
            joined=_fmt_date(record.get("joined_at")),
            status=record.get("status", "active").title(),
        )
        await _edit(update, body, keyboards.back_only())

    elif action == "checklist":
        text, items = _render_checklist(user.id)
        in_onboarding = onboarding_handlers.needs_onboarding(user.id)
        cfg = onboarding_config.get()
        await _edit(
            update,
            text,
            keyboards.checklist_keyboard(
                items,
                onboarding=in_onboarding,
                continue_label=cfg.btn_continue,
            ),
        )

    elif action == "support":
        await _edit(update, texts.SUPPORT_TEXT, keyboards.back_only())

    elif action == "help":
        body = texts.HELP_TEXT
        if is_admin(user.id):
            body += texts.HELP_ADMIN_EXTRA
        await _edit(update, body, keyboards.back_only())

    elif action == "admin":
        if not is_admin(user.id):
            await update.callback_query.answer(texts.UNAUTHORIZED, show_alert=True)
            return
        await show_admin_panel(update, context, edit=True)

    elif action == "stats":
        if not is_admin(user.id):
            await update.callback_query.answer(texts.UNAUTHORIZED, show_alert=True)
            return
        s = storage.stats()
        body = texts.STATS_TEMPLATE.format(
            total=s["total"],
            active=s["active"],
            banned=s["banned"],
            new_today=s["new_today"],
            phase="2 — Telegram Bot Build",
        )
        await _edit(update, body, keyboards.back_only())

    elif action == "broadcast_hint":
        if not is_admin(user.id):
            await update.callback_query.answer(texts.UNAUTHORIZED, show_alert=True)
            return
        await _edit(update, texts.BROADCAST_USAGE, keyboards.back_only())

    elif action == "close":
        try:
            await update.callback_query.delete_message()
        except BadRequest:
            pass


# ---------- checklist actions ----------

def _render_checklist(user_id: int) -> tuple[str, list[dict]]:
    cfg = onboarding_config.get()
    done_map = storage.get_checklist(user_id)
    items = [
        {"id": item.id, "title": item.title, "done": done_map.get(item.id, False)}
        for item in cfg.checklist_items
    ]
    done = sum(1 for it in items if it["done"])
    total = len(items)
    bar = _progress_bar_str(done, total)

    if done == total and storage.is_fully_activated(user_id):
        text = cfg.completion_message.format(
            first_name=(storage.get_user(user_id) or {}).get("first_name") or "there"
        )
    else:
        text = f"{cfg.checklist_intro}\n\nProgress: {done}/{total}  {bar}"
    return text, items


def _progress_bar_str(done: int, total: int, width: int = 10) -> str:
    if total == 0:
        return ""
    filled = round(width * done / total)
    return "▰" * filled + "▱" * (width - filled)


async def _handle_checklist(update: Update, context, args: list[str]) -> None:
    """Toggle a task and re-render the checklist in place."""
    if not args or args[0] != "toggle" or len(args) < 2:
        return
    user = update.effective_user
    item_id = args[1]
    new_state = storage.toggle_checklist_item(user.id, item_id)
    await update.callback_query.answer(
        "Marked complete ✅" if new_state else "Unmarked", show_alert=False
    )

    cfg = onboarding_config.get()
    item_title = next(
        (item.title for item in cfg.checklist_items if item.id == item_id),
        item_id,
    )
    await airtable_sync.checklist_item_toggled(
        telegram_user_id=user.id,
        task_id=item_id,
        task_title=item_title,
        completed=new_state,
    )

    text, items = _render_checklist(user.id)
    in_onboarding = onboarding_handlers.needs_onboarding(user.id)
    cfg = onboarding_config.get()
    await _edit(
        update,
        text,
        keyboards.checklist_keyboard(
            items,
            onboarding=in_onboarding,
            continue_label=cfg.btn_continue,
        ),
    )


# ---------- broadcast actions ----------

async def _handle_broadcast(update: Update, context, args: list[str]) -> None:
    """Confirm or cancel a pending broadcast (set by /broadcast command)."""
    user = update.effective_user
    if not is_admin(user.id):
        await update.callback_query.answer(texts.UNAUTHORIZED, show_alert=True)
        return

    action = args[0] if args else ""
    pending = context.user_data.get("pending_broadcast")

    if action == "cancel" or not pending:
        context.user_data.pop("pending_broadcast", None)
        await _edit(update, texts.BROADCAST_CANCELLED, keyboards.back_only())
        return

    if action == "confirm":
        targets = storage.list_active_user_ids()
        sent, failed = 0, 0
        for uid in targets:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=pending,
                    parse_mode=ParseMode.MARKDOWN,
                )
                sent += 1
            except Exception as e:
                logger.warning(f"Broadcast to {uid} failed: {e}")
                failed += 1
        context.user_data.pop("pending_broadcast", None)
        await _edit(
            update,
            texts.BROADCAST_SENT.format(count=sent, failed=failed),
            keyboards.back_only(),
        )
