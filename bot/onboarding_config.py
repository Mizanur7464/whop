"""
Load and validate the onboarding configuration.

The buyer edits `data/onboarding.json` to customize:
    * welcome / rules / completion messages
    * the list of checklist items
    * reminder cadence

We validate with Pydantic so a typo breaks loudly at startup rather
than silently producing a broken onboarding.

Hot reload:
    onboarding_config.reload() refreshes from disk without restart.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import List, Optional

from loguru import logger
from pydantic import BaseModel, Field, field_validator

CONFIG_PATH = Path("data/onboarding.json")


class ChecklistItem(BaseModel):
    id: str
    title: str
    description: str = ""
    self_mark: bool = True


class OnboardingConfig(BaseModel):
    version: int = 1
    reminder_hours: int = Field(default=24, ge=1, le=168)
    max_reminders: int = Field(default=2, ge=0, le=10)

    welcome_message: str
    location_message: str = "Where do you live? Select one option below."
    # Legacy — no longer shown in flow; kept so old JSON configs still load.
    continue_prompt: str = ""
    # Optional: buyer may not want rules/guidelines if the community is read-only.
    rules: List[str] = Field(default_factory=list)
    rules_message: Optional[str] = None
    checklist_intro: str
    checklist_items: List[ChecklistItem]
    contact_intro_message: str = ""
    contact_email_prompt: str = "Please reply with your email address in your next message."
    contact_phone_prompt: str = (
        "Thank you. Now please reply with your phone number (include country code)."
    )
    contact_saved_message: str = "Contact details saved. Tap Continue to proceed."
    confirmation_warning_message: str = (
        "Have you gone through the whole document and set everything up correctly?\n\n"
        "If you did not, this can have a negative affect on your trading experience."
    )
    completion_message: str
    screenshot_request_message: str = (
        "Please submit a screenshot showing you have linked your account to us.\n\n"
        "We will manually check your screenshot and give you access to the rest "
        "of the community when we approve."
    )
    pending_review_message: str = (
        "Thank you — we received your screenshot.\n\n"
        "Our team is reviewing it now. You will be given access within 24h. "
        "You will receive a notification when access has been granted."
    )
    approved_message: str = (
        "You are approved. Check this chat for your main group invite link. "
        "Welcome to the full Fusion Wealth community."
    )
    idle_after_complete_message: str = (
        "You're all set — onboarding is complete. "
        "You have full access to the Fusion Wealth community."
    )
    rejected_message: str = (
        "We could not approve this screenshot.\n\n{reason}\n\n"
        "Please send a new screenshot when you are ready."
    )
    btn_next: str = "Next"
    btn_continue: str = "Continue"
    btn_everything_set_up: str = "Everything is set up"

    @field_validator("checklist_items")
    @classmethod
    def _unique_ids(cls, items: list[ChecklistItem]) -> list[ChecklistItem]:
        seen: set[str] = set()
        for item in items:
            if item.id in seen:
                raise ValueError(f"duplicate checklist item id: {item.id}")
            seen.add(item.id)
        if not items:
            raise ValueError("checklist_items must not be empty")
        return items


_lock = Lock()
_cached: OnboardingConfig | None = None


def _load_from_disk() -> OnboardingConfig:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Onboarding config missing at {CONFIG_PATH}. "
            "Copy data/onboarding.json from the repo template."
        )
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    cfg = OnboardingConfig.model_validate(raw)
    logger.info(
        f"Onboarding config loaded (v{cfg.version}, "
        f"{len(cfg.checklist_items)} tasks, reminder={cfg.reminder_hours}h)"
    )
    return cfg


def get() -> OnboardingConfig:
    """Return the cached config, loading on first access."""
    global _cached
    if _cached is None:
        with _lock:
            if _cached is None:
                _cached = _load_from_disk()
    return _cached


def reload() -> OnboardingConfig:
    """Reload from disk (admin /reload command)."""
    global _cached
    with _lock:
        _cached = _load_from_disk()
    return _cached
