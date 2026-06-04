"""
/checklist — onboarding task tracker.

Pulls the canonical task list from `data/onboarding.json` via the
`onboarding_config` module. Per-user progress lives in storage so the
same set of items is reusable across users.
"""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot import keyboards, onboarding_config, storage
from bot.access import idle_after_complete_message, shows_main_menu
from bot.channel_context import ensure_private_dm
from bot.community_layout import FLOW_WELCOME
from bot.decorators import log_call


def _progress_bar(done: int, total: int, width: int = 10) -> str:
    if total == 0:
        return ""
    filled = round(width * done / total)
    return "▰" * filled + "▱" * (width - filled)


def _render(user_id: int) -> tuple[str, list[dict]]:
    cfg = onboarding_config.get()
    done_map = storage.get_checklist(user_id)
    items = [
        {"id": item.id, "title": item.title, "done": done_map.get(item.id, False)}
        for item in cfg.checklist_items
    ]
    done = sum(1 for it in items if it["done"])
    total = len(items)
    bar = _progress_bar(done, total)

    if done == total:
        text = cfg.completion_message
    else:
        text = f"{cfg.checklist_intro}\n\nProgress: {done}/{total}  {bar}"
    return text, items


@log_call
async def cmd_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_private_dm(
        update, context, flow=FLOW_WELCOME, command="checklist"
    ):
        return

    user = update.effective_user
    if not shows_main_menu(user.id):
        await update.message.reply_text(idle_after_complete_message())
        return

    text, items = _render(user.id)
    await update.message.reply_text(
        text,
        reply_markup=keyboards.checklist_keyboard(items),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
