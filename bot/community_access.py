"""Chat IDs used when granting or revoking Telegram community access."""

from __future__ import annotations

from config import settings


def community_chat_ids() -> list[int]:
    """Groups/channels the bot should add to or remove from."""
    ids: list[int] = []
    seen: set[int] = set()
    for value in (
        settings.telegram_main_group_id,
        settings.telegram_vip_group_id,
        settings.welcome_channel_id,
        settings.copy_trading_channel_id,
        settings.support_channel_id,
        settings.signals_channel_id,
        settings.education_channel_id,
        settings.pnl_channel_id,
    ):
        if isinstance(value, int) and value not in seen:
            seen.add(value)
            ids.append(value)
    return ids
