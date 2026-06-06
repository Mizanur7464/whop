"""
Community layout: one Telegram group with forum topics (threads).

Set in .env:
    TELEGRAM_COMMUNITY_LAYOUT=topics
    TELEGRAM_MAIN_GROUP_ID=-100...
    TELEGRAM_TOPIC_WELCOME=2
    TELEGRAM_TOPIC_COPYTRADING=3
    ...

Legacy mode (separate channels) still works when TELEGRAM_COMMUNITY_LAYOUT=channels
and TELEGRAM_*_CHANNEL_ID values are set.
"""

from __future__ import annotations

from typing import Optional

from telegram import Update

from config import settings

FLOW_WELCOME = "welcome"
FLOW_COPYTRADING = "copytrading"
FLOW_SUPPORT = "support"
FLOW_SIGNALS = "signals"
FLOW_EDUCATION = "education"
FLOW_PNL = "pnl"
FLOW_NOTIFICATIONS = "notifications"

_FLOW_TOPIC_ATTR = {
    FLOW_WELCOME: "telegram_topic_welcome",
    FLOW_COPYTRADING: "telegram_topic_copytrading",
    FLOW_SUPPORT: "telegram_topic_support",
    FLOW_SIGNALS: "telegram_topic_signals",
    FLOW_EDUCATION: "telegram_topic_education",
    FLOW_PNL: "telegram_topic_pnl",
    FLOW_NOTIFICATIONS: "telegram_topic_notifications",
}

_FLOW_CHANNEL_ATTR = {
    FLOW_WELCOME: "welcome_channel_id",
    FLOW_COPYTRADING: "copy_trading_channel_id",
    FLOW_SUPPORT: "support_channel_id",
    FLOW_SIGNALS: "signals_channel_id",
    FLOW_EDUCATION: "education_channel_id",
    FLOW_PNL: "pnl_channel_id",
}

_FLOW_LABEL = {
    FLOW_WELCOME: "Welcome",
    FLOW_COPYTRADING: "Copy Trading",
    FLOW_SUPPORT: "Support",
    FLOW_SIGNALS: "Signals",
    FLOW_EDUCATION: "Members Community",
    FLOW_PNL: "PnL",
    FLOW_NOTIFICATIONS: "Daily Notifications",
}


def uses_topics_mode() -> bool:
    layout = (settings.telegram_community_layout or "topics").strip().lower()
    return layout == "topics" and settings.telegram_main_group_id is not None


def uses_channels_mode() -> bool:
    return not uses_topics_mode()


def main_group_id() -> int | None:
    return settings.telegram_main_group_id


def topic_id_for(flow: str) -> int | None:
    attr = _FLOW_TOPIC_ATTR.get(flow)
    if not attr:
        return None
    return getattr(settings, attr, None)


def channel_id_for(flow: str) -> int | None:
    attr = _FLOW_CHANNEL_ATTR.get(flow)
    if not attr:
        return None
    return getattr(settings, attr, None)


def flow_label(flow: str) -> str:
    return _FLOW_LABEL.get(flow, flow.title())


def current_thread_id(update: Update) -> int | None:
    msg = update.effective_message
    if msg and msg.message_thread_id:
        return msg.message_thread_id
    cq = update.callback_query
    if cq and cq.message and cq.message.message_thread_id:
        return cq.message.message_thread_id
    return None


def is_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type == "private")


def is_main_group(update: Update) -> bool:
    gid = main_group_id()
    if not gid:
        return False
    chat = update.effective_chat
    return bool(chat and chat.id == gid)


def message_thread_kwargs(update: Update, flow: str | None = None) -> dict:
    """
    Reply in the same topic the user clicked from.
    Do not force .env topic IDs here — wrong IDs cause 'message thread not found'.
    """
    thread = current_thread_id(update)
    if thread is not None:
        return {"message_thread_id": thread}
    return {}


def unlock_topic_flows() -> list[str]:
    """Topics to mention after welcome approval (non-welcome flows)."""
    return [
        f
        for f in (
            FLOW_SIGNALS,
            FLOW_EDUCATION,
            FLOW_NOTIFICATIONS,
            FLOW_PNL,
            FLOW_COPYTRADING,
            FLOW_SUPPORT,
        )
        if topic_id_for(f) is not None or channel_id_for(f) is not None
    ]


def build_unlock_dm_text() -> str:
    """Approval DM body shown above the main group invite link."""
    return (
        "You are approved. Welcome to Fusion Strategy. "
        "You now have access to the full community. Click the link below."
    )
