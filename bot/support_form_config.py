"""Load support channel form config from ``data/layout/support_form.json``."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import List, Optional

from loguru import logger
from pydantic import BaseModel

CONFIG_PATH = Path("data/layout/support_form.json")


class FormQuestion(BaseModel):
    id: str
    prompt: str


class SupportFormConfig(BaseModel):
    version: int = 1
    welcome_message: str
    btn_continue: str = "Continue"
    form_intro: str
    form_questions: List[FormQuestion]
    btn_submit: str = "Submit"
    submitted_message: str


_lock = Lock()
_cached: Optional[SupportFormConfig] = None


def _load_from_disk() -> SupportFormConfig:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing support form config: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = SupportFormConfig.model_validate(json.load(f))
    logger.info(
        f"Support form config loaded (v{cfg.version}, questions={len(cfg.form_questions)})"
    )
    return cfg


def get() -> SupportFormConfig:
    global _cached
    if _cached is None:
        with _lock:
            if _cached is None:
                _cached = _load_from_disk()
    return _cached


def reload() -> SupportFormConfig:
    global _cached
    with _lock:
        _cached = _load_from_disk()
    return _cached
