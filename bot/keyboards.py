"""
All inline keyboards live here.

Callback-data convention:
    "<feature>:<action>[:<param>]"
Examples:
    "menu:profile"            — open profile screen
    "menu:back"               — return to main menu
    "checklist:toggle:3"      — toggle task ID 3
    "broadcast:confirm"       — confirm pending broadcast
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot import texts


# ---------- Main menu ----------

def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(texts.BTN_PROFILE, callback_data="menu:profile"),
            InlineKeyboardButton(texts.BTN_CHECKLIST, callback_data="menu:checklist"),
        ],
        [
            InlineKeyboardButton(texts.BTN_SUPPORT, callback_data="menu:support"),
            InlineKeyboardButton(texts.BTN_HELP, callback_data="menu:help"),
        ],
    ]
    if is_admin:
        rows.append(
            [
                InlineKeyboardButton(
                    texts.BTN_ADMIN_PANEL, callback_data="menu:admin"
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    texts.BTN_ADMIN_STATS, callback_data="menu:stats"
                ),
                InlineKeyboardButton(
                    texts.BTN_ADMIN_BROADCAST, callback_data="menu:broadcast_hint"
                ),
            ]
        )
    return InlineKeyboardMarkup(rows)


# ---------- Back-to-menu button ----------

def back_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.BTN_BACK, callback_data="menu:home")]]
    )


def close_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.BTN_CLOSE, callback_data="menu:close")]]
    )


# ---------- Checklist keyboard ----------

def checklist_keyboard(
    items: list[dict],
    *,
    onboarding: bool = False,
    continue_label: str = "Continue",
) -> InlineKeyboardMarkup:
    """
    Render checklist items as toggle buttons.

    items = [{"id": "1", "title": "Watch intro", "done": False}, ...]
    """
    rows = []
    for item in items:
        prefix = "✅" if item["done"] else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{prefix} {item['title']}",
                    callback_data=f"checklist:toggle:{item['id']}",
                )
            ]
        )
    if onboarding:
        if items and all(item["done"] for item in items):
            rows.append(
                [
                    InlineKeyboardButton(
                        continue_label, callback_data="onb:continue"
                    )
                ]
            )
    else:
        rows.append([InlineKeyboardButton(texts.BTN_BACK, callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def copytrading_checklist_keyboard(
    items: list[dict],
    *,
    continue_label: str = "Continue",
) -> InlineKeyboardMarkup:
    """Copy-trading checklist — callbacks use ``ct:chk:`` prefix."""
    rows = []
    for item in items:
        prefix = "✅" if item["done"] else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{prefix} {item['title']}",
                    callback_data=f"ct:chk:{item['id']}",
                )
            ]
        )
    if items and all(item["done"] for item in items):
        rows.append(
            [InlineKeyboardButton(continue_label, callback_data="ct:continue")]
        )
    return InlineKeyboardMarkup(rows)


# ---------- Broadcast confirm ----------

def broadcast_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Send", callback_data="broadcast:confirm"),
                InlineKeyboardButton("❌ Cancel", callback_data="broadcast:cancel"),
            ]
        ]
    )
