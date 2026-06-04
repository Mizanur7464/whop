"""Who sees the main menu vs. onboarding-only idle state."""

from __future__ import annotations

from bot import onboarding_config, storage
from bot.decorators import is_admin


def shows_main_menu(user_id: int) -> bool:
    """Main menu is for admins and users still in welcome onboarding."""
    if is_admin(user_id):
        return True
    return not storage.is_fully_activated(user_id)


def idle_after_complete_message() -> str:
    return onboarding_config.get().idle_after_complete_message
