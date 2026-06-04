"""
Community unlock after welcome approval.

topics mode: one invite link to TELEGRAM_MAIN_GROUP_ID + DM listing forum topics.
channels mode: one-time invite links per TELEGRAM_*_CHANNEL_ID.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from bot.community_layout import build_unlock_dm_text, uses_topics_mode
from config import settings
from integrations import telegram_ops

UNLOCK_CONFIG_PATH = Path("data/layout/community_unlock.json")


def _load_unlock_config() -> dict:
    if not UNLOCK_CONFIG_PATH.exists():
        return {"unlock_channels": []}
    with UNLOCK_CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _env_channel_ids() -> list[int]:
    cfg = _load_unlock_config()
    keys = cfg.get("unlock_channels") or []
    attr_map = {
        "TELEGRAM_WELCOME_CHANNEL_ID": "welcome_channel_id",
        "TELEGRAM_COPYTRADING_CHANNEL_ID": "copy_trading_channel_id",
        "TELEGRAM_OFFBOARD_CHANNEL_ID": "offboard_channel_id",
        "TELEGRAM_SUPPORT_CHANNEL_ID": "support_channel_id",
        "TELEGRAM_SIGNALS_CHANNEL_ID": "signals_channel_id",
        "TELEGRAM_EDUCATION_CHANNEL_ID": "education_channel_id",
        "TELEGRAM_PNL_CHANNEL_ID": "pnl_channel_id",
    }
    ids: list[int] = []
    for key in keys:
        attr = attr_map.get(key)
        if not attr:
            continue
        value = getattr(settings, attr, None)
        if isinstance(value, int):
            ids.append(value)
    out: list[int] = []
    seen: set[int] = set()
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


async def _unlock_topics_mode(telegram_user_id: int) -> dict:
    gid = settings.telegram_main_group_id
    if not gid:
        logger.warning("unlock_for_user: TELEGRAM_MAIN_GROUP_ID not set")
        return {"ok": False, "reason": "no_main_group", "channels": []}

    body = build_unlock_dm_text()

    if settings.safe_mode:
        logger.info("SAFE_MODE enabled — not generating group invite")
        await telegram_ops.dm(
            telegram_user_id,
            f"✅ Setup complete. (SAFE_MODE — no invite sent yet.)\n\n{body}",
            parse_mode=None,
        )
        return {"ok": True, "safe_mode": True, "channels": [gid]}

    link = await telegram_ops.generate_invite_link(gid, name="fusion-welcome")
    if link:
        text = f"{body}\n\nJoin the community:\n{link}"
    else:
        text = (
            f"{body}\n\n"
            "We could not generate an invite link automatically. "
            "An admin will add you to the group."
        )
    ok = await telegram_ops.dm(telegram_user_id, text, parse_mode=None)
    return {"ok": ok, "safe_mode": False, "channels": [gid], "mode": "topics"}


async def unlock_for_user(telegram_user_id: int) -> dict:
    if uses_topics_mode():
        return await _unlock_topics_mode(telegram_user_id)

    channel_ids = _env_channel_ids()
    if not channel_ids:
        logger.warning("unlock_for_user: no unlock channels configured yet")
        return {"ok": False, "reason": "no_channels_configured", "channels": []}

    if settings.safe_mode:
        logger.info("SAFE_MODE enabled — not generating invite links")
        await telegram_ops.dm(
            telegram_user_id,
            "✅ Setup complete. (SAFE_MODE is enabled, so invites are not being sent yet.)",
            parse_mode=None,
        )
        return {"ok": True, "safe_mode": True, "channels": channel_ids}

    result = await telegram_ops.grant_access(
        telegram_user_id,
        channel_ids,
        plan_name="Fusion Wealth",
    )
    return {"ok": bool(result.get("sent")), "safe_mode": False, "channels": channel_ids}
