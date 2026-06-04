"""Load copy-trading channel flow config from ``data/layout/copy_trading.json``."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import List, Optional

from loguru import logger
from pydantic import BaseModel, Field, field_validator

from bot.welcome_docs import DocRef

CONFIG_PATH = Path("data/layout/copy_trading.json")


class ChecklistItem(BaseModel):
    id: str
    title: str


class PlatformOption(BaseModel):
    id: str
    label: str
    doc: DocRef


class CopyTradingConfig(BaseModel):
    version: int = 1
    welcome_message: str
    btn_setup: str = "Set up copy trading"
    platform_prompt: str = "What platform are you using?"
    platforms: List[PlatformOption] = Field(default_factory=list)
    checklist_intro: str
    checklist_items: List[ChecklistItem]
    confirmation_warning_message: str
    success_message: str
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
_cached: Optional[CopyTradingConfig] = None


def _load_from_disk() -> CopyTradingConfig:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing copy trading config: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = CopyTradingConfig.model_validate(json.load(f))
    logger.info(
        f"Copy trading config loaded (v{cfg.version}, "
        f"platforms={len(cfg.platforms)}, checklist={len(cfg.checklist_items)})"
    )
    return cfg


def get() -> CopyTradingConfig:
    global _cached
    if _cached is None:
        with _lock:
            if _cached is None:
                _cached = _load_from_disk()
    return _cached


def reload() -> CopyTradingConfig:
    global _cached
    with _lock:
        _cached = _load_from_disk()
    return _cached


def platform_by_id(platform_id: str) -> Optional[PlatformOption]:
    for p in get().platforms:
        if p.id == platform_id:
            return p
    return None
