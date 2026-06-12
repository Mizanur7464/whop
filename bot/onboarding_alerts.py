"""Notify admins when a member hits an onboarding error or blocked step."""

from __future__ import annotations

import html
import time
from typing import TYPE_CHECKING

from loguru import logger
from telegram.constants import ParseMode

from bot import storage
from config import settings

if TYPE_CHECKING:
    from telegram import User
    from telegram.ext import ContextTypes

ONBOARDING_STEP_KEY = "onboarding_step"

STEP_LABELS: dict[str, str] = {
    "welcome": "Welcome",
    "location": "Location selection",
    "location_pdf": "Location PDF",
    "checklist": "Checklist",
    "continue": "Confirmation",
    "contact": "Contact details",
    "contact_first_name": "Contact — first name",
    "contact_last_name": "Contact — last name",
    "contact_email": "Contact — email",
    "contact_phone": "Contact — phone",
    "contact_platform_id": "Contact — platform user ID",
    "terms": "Terms & Conditions",
    "terms_accept": "Terms accept",
    "screenshot": "Screenshot upload",
    "callback": "Button action",
}

# (user_id, step) -> monotonic expiry — avoid duplicate alerts on rapid retries
_dedupe_until: dict[tuple[int, str], float] = {}
_DEDUPE_SEC = 600.0


def all_onboarding_admin_ids() -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for admin_id in (
        *settings.telegram_admin_ids,
        *settings.onboarding_review_admin_ids,
    ):
        if admin_id not in seen:
            seen.add(admin_id)
            ordered.append(admin_id)
    return ordered


def set_onboarding_step(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, step: str
) -> None:
    context.user_data[ONBOARDING_STEP_KEY] = step
    storage.upsert_user(user_id, onboarding_step=step)


def current_onboarding_step(
    context: ContextTypes.DEFAULT_TYPE | None, user_id: int | None
) -> str | None:
    if context and context.user_data.get(ONBOARDING_STEP_KEY):
        return str(context.user_data[ONBOARDING_STEP_KEY])
    if user_id:
        record = storage.get_user(user_id) or {}
        raw = record.get("onboarding_step")
        if raw:
            return str(raw)
    return None


def _user_line(user: User) -> str:
    name = html.escape(
        " ".join(p for p in [user.first_name, user.last_name] if p) or "—"
    )
    username = (
        f"@{html.escape(user.username)}"
        if user.username
        else "no username"
    )
    return f"{name} ({username}, ID <code>{user.id}</code>)"


async def notify_admins_onboarding_issue(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user: User,
    step: str,
    detail: str,
    error: BaseException | None = None,
) -> None:
    """DM all onboarding admins — best effort, never raises."""
    admin_ids = all_onboarding_admin_ids()
    if not admin_ids:
        logger.error(
            "onboarding_alerts: no TELEGRAM_ADMIN_IDS / TELEGRAM_REVIEW_ADMIN_IDS"
        )
        return

    now = time.monotonic()
    dedupe_key = (user.id, step)
    if _dedupe_until.get(dedupe_key, 0) > now:
        return
    _dedupe_until[dedupe_key] = now + _DEDUPE_SEC

    label = STEP_LABELS.get(step, step.replace("_", " ").title())
    err_line = ""
    if error is not None:
        err_line = f"\n• Error: <code>{html.escape(str(error))[:400]}</code>"

    body = (
        "⚠️ <b>Onboarding issue</b>\n\n"
        f"• Member: {_user_line(user)}\n"
        f"• Step: <b>{html.escape(label)}</b>\n"
        f"• Detail: {html.escape(detail[:500])}"
        f"{err_line}\n\n"
        "Reach out in Telegram if they need help."
    )

    for admin_id in admin_ids:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=body,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(
                f"onboarding_alerts: could not notify admin {admin_id}: {e}"
            )
