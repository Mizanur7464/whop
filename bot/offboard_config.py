"""Load offboard channel config from ``data/layout/offboard.json``."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import List, Optional

from loguru import logger
from pydantic import BaseModel, Field

from bot.welcome_docs import DocRef

CONFIG_PATH = Path("data/layout/offboard.json")


class FormQuestion(BaseModel):
    id: str
    prompt: str


class PlatformOption(BaseModel):
    id: str
    label: str
    doc: DocRef


class OffboardConfig(BaseModel):
    version: int = 1
    welcome_message: str
    btn_offboard: str = "Offboard"
    platform_prompt: str
    after_doc_message: str
    btn_continue: str = "Continue"
    platforms: List[PlatformOption] = Field(default_factory=list)
    form_intro: str
    form_questions: List[FormQuestion]
    btn_submit: str = "Submit"
    submitted_message: str


_lock = Lock()
_cached: Optional[OffboardConfig] = None


def _load_from_disk() -> OffboardConfig:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing offboard config: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = OffboardConfig.model_validate(json.load(f))
    logger.info(
        f"Offboard config loaded (v{cfg.version}, platforms={len(cfg.platforms)}, "
        f"questions={len(cfg.form_questions)})"
    )
    return cfg


def get() -> OffboardConfig:
    global _cached
    if _cached is None:
        with _lock:
            if _cached is None:
                _cached = _load_from_disk()
    return _cached


def reload() -> OffboardConfig:
    global _cached
    with _lock:
        _cached = _load_from_disk()
    return _cached


def platform_by_id(platform_id: str) -> Optional[PlatformOption]:
    for p in get().platforms:
        if p.id == platform_id:
            return p
    return None
