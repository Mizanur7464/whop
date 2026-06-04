"""Load terms & conditions step config from ``data/layout/terms.json``."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from pydantic import BaseModel

CONFIG_PATH = Path("data/layout/terms.json")
_lock = Lock()
_cache: TermsConfig | None = None


class TermsDoc(BaseModel):
    type: str = "file"
    path: str = ""
    url: str = ""
    caption: str = ""


class TermsConfig(BaseModel):
    version: int = 1
    message: str
    btn_accept: str = "Accept"
    doc: TermsDoc


def _load_from_disk() -> TermsConfig:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing terms config: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return TermsConfig.model_validate(json.load(f))


def get() -> TermsConfig:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load_from_disk()
        return _cache


def reload() -> TermsConfig:
    global _cache
    with _lock:
        _cache = _load_from_disk()
        return _cache
