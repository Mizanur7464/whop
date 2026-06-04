"""
Location-based onboarding document distribution (EU/UAE).

The buyer's desired flow:
    1) User enters the Welcome channel
    2) Bot asks where they are located (Inside UAE vs Outside UAE)
    3) Based on selection, bot shares the correct branded PDF
    4) User completes a 4-step checklist
    5) Only then, the rest of the community is unlocked

Config is stored in `data/layout/welcome_docs.json` so buyer can change
copy and file paths without touching code (admin can reload later).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Literal, Optional

from loguru import logger
from pydantic import BaseModel, Field


CONFIG_PATH = Path("data/layout/welcome_docs.json")


class DocRef(BaseModel):
    type: Literal["file", "url"] = "file"
    path: Optional[str] = None
    url: Optional[str] = None
    caption: str = ""


class LocationConfig(BaseModel):
    id: str
    label: str
    platform: str
    doc: DocRef


class ChecklistItem(BaseModel):
    id: str
    title: str
    self_mark: bool = True


class WelcomeDocsConfig(BaseModel):
    version: int = 1
    brand_name: str = "Fusion Wealth"
    locations: list[LocationConfig] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)


_lock = Lock()
_cached: WelcomeDocsConfig | None = None


def _load() -> WelcomeDocsConfig:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing welcome docs config: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    cfg = WelcomeDocsConfig.model_validate(raw)
    logger.info(
        f"Welcome docs config loaded (v{cfg.version}, locations={len(cfg.locations)}, "
        f"checklist={len(cfg.checklist)})"
    )
    return cfg


def get() -> WelcomeDocsConfig:
    global _cached
    if _cached is None:
        with _lock:
            if _cached is None:
                _cached = _load()
    return _cached


def reload() -> WelcomeDocsConfig:
    global _cached
    with _lock:
        _cached = _load()
    return _cached


def location_by_id(location_id: str) -> Optional[LocationConfig]:
    cfg = get()
    for loc in cfg.locations:
        if loc.id == location_id:
            return loc
    return None

