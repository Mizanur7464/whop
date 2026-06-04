"""Load leave-group survey copy from ``data/layout/leave_survey.json``."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from pydantic import BaseModel

CONFIG_PATH = Path("data/layout/leave_survey.json")
_lock = Lock()
_cache: LeaveSurveyConfig | None = None


class LeaveSurveyConfig(BaseModel):
    version: int = 2
    dm_message: str
    btn_submit_reason: str = "Submit reason"
    reason_prompt: str = "Please type your reason in your next message and send it."
    thanks_message: str = "Thank you for your feedback."


def get() -> LeaveSurveyConfig:
    global _cache
    if _cache is None:
        with _lock:
            if _cache is None:
                with CONFIG_PATH.open("r", encoding="utf-8") as f:
                    _cache = LeaveSurveyConfig.model_validate(json.load(f))
    return _cache


def reload() -> LeaveSurveyConfig:
    global _cache
    with _lock:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            _cache = LeaveSurveyConfig.model_validate(json.load(f))
    return _cache
