"""
Telegram-side operations driven by Whop events.

The bot's Application instance is set once at startup via `set_bot(app)`,
then handlers throughout the codebase can call these helpers without
having to thread the bot through every function signature.

Capabilities:
    * generate_invite_link(chat_id)  - one-use, 24h invite link
    * grant_access(telegram_user_id, chats) - DM the user with invite links
    * revoke_access(telegram_user_id, chats) - kick + unban (so they can rejoin if invited)
    * dm(user_id, text)              - safe DM (errors logged, never raised)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from loguru import logger
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application

from config import settings
from integrations.whop_copy import grant_access_invite_footer

_app: Optional[Application] = None


def chat_label(chat_id: int) -> str:
    """Human label for invite links on the Whop success page."""
    if chat_id == settings.telegram_main_group_id:
        return "Main community"
    if chat_id == settings.telegram_vip_group_id:
        return "VIP group"
    if chat_id == settings.telegram_announcement_channel_id:
        return "Announcements"
    return "Telegram group"


def set_bot(app: Application) -> None:
    """Called once during startup so other modules can reach the bot."""
    global _app
    _app = app


def bot() -> Bot:
    if _app is None:
        raise RuntimeError("telegram_ops.set_bot() not called yet")
    return _app.bot


# ---------- DMs ----------

async def dm(user_id: int, text: str, **kwargs) -> bool:
    """Send a DM. Return True on success, False on any failure (logged)."""
    parse_mode = kwargs.pop("parse_mode", ParseMode.MARKDOWN)
    disable_preview = kwargs.pop("disable_web_page_preview", True)
    try:
        await bot().send_message(
            chat_id=user_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_preview,
            **kwargs,
        )
        return True
    except BadRequest as e:
        if parse_mode is not None and "can't parse entities" in str(e).lower():
            logger.debug(f"DM to {user_id}: retry without parse_mode")
            try:
                await bot().send_message(
                    chat_id=user_id,
                    text=text,
                    disable_web_page_preview=disable_preview,
                    **kwargs,
                )
                return True
            except TelegramError as e2:
                logger.warning(f"DM to {user_id} failed: {e2}")
        else:
            logger.warning(f"DM to {user_id} failed: {e}")
    except Forbidden:
        logger.info(f"DM blocked by user {user_id} (hasn't started the bot)")
    except TelegramError as e:
        logger.warning(f"DM to {user_id} failed: {e}")
    return False


# ---------- Invite links ----------

async def generate_invite_link(
    chat_id: int,
    *,
    expire_in_minutes: int = 60 * 24,
    member_limit: int = 1,
    name: str | None = None,
    bot_instance: Bot | None = None,
) -> Optional[str]:
    """
    Create a one-time invite link. The bot must be an admin in `chat_id`
    with the 'invite users' permission.
    """
    tg = bot_instance or bot()
    try:
        expire_date = datetime.now(timezone.utc) + timedelta(minutes=expire_in_minutes)
        link = await tg.create_chat_invite_link(
            chat_id=chat_id,
            expire_date=expire_date,
            member_limit=member_limit,
            name=name or f"auto-{int(expire_date.timestamp())}",
        )
        return link.invite_link
    except TelegramError as e:
        logger.error(f"create_chat_invite_link failed for chat {chat_id}: {e}")
        return None


async def create_main_group_invite(
    *, name: str = "claim", bot_instance: Bot | None = None
) -> str | None:
    """One-time invite for TELEGRAM_MAIN_GROUP_ID (claim + success page)."""
    gid = settings.telegram_main_group_id
    if not gid:
        logger.error("create_main_group_invite: TELEGRAM_MAIN_GROUP_ID not set")
        return None
    return await generate_invite_link(gid, name=name, bot_instance=bot_instance)


async def build_invite_link_list(
    chat_ids: Iterable[int],
    *,
    plan_name: str = "membership",
) -> list[dict[str, str]]:
    """
    Create one-time invite links for the success page (no Telegram user required).

    Returns [{"label": "Main community", "url": "https://t.me/+..."}, ...].
    """
    out: list[dict[str, str]] = []
    for chat_id in chat_ids:
        url = await generate_invite_link(
            chat_id,
            name=f"whop-{plan_name}-{chat_id}",
        )
        if url:
            out.append({"label": chat_label(chat_id), "url": url})
    return out


# ---------- Grant access ----------

async def grant_access(
    telegram_user_id: int,
    chat_ids: Iterable[int],
    *,
    plan_name: str = "your plan",
) -> dict:
    """
    Generate invite links for every chat in `chat_ids` and DM them to the user.

    Returns a result dict for logging/storage:
        {"sent": bool, "links": {chat_id: url|None}}
    """
    links: dict[int, str | None] = {}
    for chat_id in chat_ids:
        links[chat_id] = await generate_invite_link(chat_id)

    valid_links = [(c, u) for c, u in links.items() if u]
    if not valid_links:
        logger.error(f"grant_access: no invite links could be generated for {telegram_user_id}")
        await dm(
            telegram_user_id,
            "Welcome! We couldn't generate your group invites automatically. "
            "Our team has been alerted and will reach out shortly.",
        )
        return {"sent": False, "links": links}

    lines = [
        f"🎉 *Welcome to the {plan_name.title()} community!*",
        "",
        "Tap the link(s) below to join your group(s). Each link is one-time use:",
        "",
    ]
    for idx, (_, url) in enumerate(valid_links, start=1):
        lines.append(f"{idx}. {url}")
    lines.append("")
    lines.append(grant_access_invite_footer())

    ok = await dm(telegram_user_id, "\n".join(lines))
    return {"sent": ok, "links": links}


# ---------- Revoke access ----------

async def revoke_access(
    telegram_user_id: int,
    chat_ids: Iterable[int],
    *,
    reason: str = "membership ended",
) -> dict:
    """
    Remove the user from each chat. Telegram requires ban_chat_member +
    unban_chat_member to evict cleanly (otherwise they're banned forever).
    """
    results: dict[int, str] = {}
    for chat_id in chat_ids:
        try:
            await bot().ban_chat_member(chat_id=chat_id, user_id=telegram_user_id)
            await bot().unban_chat_member(
                chat_id=chat_id, user_id=telegram_user_id, only_if_banned=True
            )
            results[chat_id] = "removed"
        except BadRequest as e:
            if "user not found" in str(e).lower() or "participant_id_invalid" in str(e).lower():
                results[chat_id] = "not_in_chat"
            else:
                logger.warning(f"revoke_access on chat {chat_id} for {telegram_user_id}: {e}")
                results[chat_id] = f"error: {e}"
        except TelegramError as e:
            logger.warning(f"revoke_access on chat {chat_id} for {telegram_user_id}: {e}")
            results[chat_id] = f"error: {e}"

    await dm(
        telegram_user_id,
        f"Your access has been removed ({reason}).\n\n"
        "If this was unexpected, reply /support and we'll help.",
    )
    return results
