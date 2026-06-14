"""Cache Telegram file_id per local PDF path to avoid re-uploading large files."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

_CACHE_PATH = Path("logs/pdf_file_ids.json")


def _load() -> dict[str, str]:
    if not _CACHE_PATH.exists():
        return {}
    try:
        with _CACHE_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return {str(k): str(v) for k, v in raw.items()}
    except Exception as e:
        logger.warning(f"pdf_cache: could not load {_CACHE_PATH}: {e}")
        return {}


def _save(data: dict[str, str]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_file_id(pdf_path: Path) -> str | None:
    key = str(pdf_path.resolve())
    return _load().get(key)


def set_file_id(pdf_path: Path, file_id: str) -> None:
    key = str(pdf_path.resolve())
    data = _load()
    if data.get(key) == file_id:
        return
    data[key] = file_id
    _save(data)
    logger.info(f"pdf_cache: stored file_id for {pdf_path.name}")
