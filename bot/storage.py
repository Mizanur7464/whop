"""
Lightweight storage abstraction.

Phase 2 uses an in-memory dict + JSON snapshot so we can develop
without Whop or Airtable wired up. In Phase 5 we swap the backend
to Airtable behind the same interface — handlers don't change.

Interface:
    get_user(user_id) -> dict | None
    upsert_user(user_id, **fields) -> dict
    set_status(user_id, status)
    list_active_user_ids() -> list[int]
    stats() -> dict
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from loguru import logger

_SNAPSHOT = Path("logs/users_snapshot.json")
_PENDING_PATH = Path("logs/pending_claims.json")
_WHOP_INDEX_PATH = Path("logs/whop_user_index.json")

_lock = Lock()
_users: dict[int, dict] = {}

# claim_code -> {"whop_user_id", "whop_membership_id", "product_id", "created_at"}
_pending_claims: dict[str, dict] = {}

# whop_user_id -> telegram_user_id (reverse lookup for webhooks)
_whop_to_tg: dict[str, int] = {}


# ---------- snapshot helpers ----------

def _save() -> None:
    _SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    with _SNAPSHOT.open("w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in _users.items()}, f, indent=2)
    with _PENDING_PATH.open("w", encoding="utf-8") as f:
        json.dump(_pending_claims, f, indent=2)
    with _WHOP_INDEX_PATH.open("w", encoding="utf-8") as f:
        json.dump(_whop_to_tg, f, indent=2)


def _load() -> None:
    if _SNAPSHOT.exists():
        try:
            with _SNAPSHOT.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            _users.update({int(k): v for k, v in raw.items()})
            logger.info(f"Storage: loaded {len(_users)} users from snapshot")
        except Exception as e:
            logger.warning(f"Storage: failed to load users snapshot ({e})")

    if _PENDING_PATH.exists():
        try:
            with _PENDING_PATH.open("r", encoding="utf-8") as f:
                _pending_claims.update(json.load(f))
            logger.info(f"Storage: loaded {len(_pending_claims)} pending claims")
        except Exception as e:
            logger.warning(f"Storage: failed to load pending claims ({e})")

    if _WHOP_INDEX_PATH.exists():
        try:
            with _WHOP_INDEX_PATH.open("r", encoding="utf-8") as f:
                _whop_to_tg.update({k: int(v) for k, v in json.load(f).items()})
            logger.info(f"Storage: loaded {len(_whop_to_tg)} Whop ID links")
        except Exception as e:
            logger.warning(f"Storage: failed to load whop index ({e})")


_load()


# ---------- public API ----------

def get_user(user_id: int) -> Optional[dict]:
    return _users.get(user_id)


def upsert_user(user_id: int, **fields) -> dict:
    """Create user if missing, otherwise update fields."""
    with _lock:
        now = datetime.now(timezone.utc).isoformat()
        user = _users.get(user_id)
        if user is None:
            user = {
                "user_id": user_id,
                "joined_at": now,
                "status": "active",
                "plan": "unknown",
                "checklist": {},
            }
            _users[user_id] = user
            logger.info(f"Storage: new user {user_id}")
        user.update(fields)
        user["updated_at"] = now
        _save()
        return user


def set_status(user_id: int, status: str) -> Optional[dict]:
    user = _users.get(user_id)
    if not user:
        return None
    return upsert_user(user_id, status=status)


def list_active_user_ids() -> list[int]:
    return [uid for uid, u in _users.items() if u.get("status") == "active"]


def stats() -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    total = len(_users)
    active = sum(1 for u in _users.values() if u.get("status") == "active")
    banned = sum(1 for u in _users.values() if u.get("status") == "banned")
    new_today = sum(
        1 for u in _users.values() if u.get("joined_at", "").startswith(today)
    )
    return {
        "total": total,
        "active": active,
        "banned": banned,
        "new_today": new_today,
    }


# ---------- Checklist sub-API ----------

def get_checklist(user_id: int) -> dict[str, bool]:
    """Return {item_id: done?} dict for a user."""
    user = get_user(user_id)
    return user.get("checklist", {}) if user else {}


def toggle_checklist_item(user_id: int, item_id: str) -> bool:
    """Flip done/undone for a single item. Returns new state."""
    with _lock:
        user = _users.get(user_id)
        if not user:
            user = upsert_user(user_id)
        current = user.setdefault("checklist", {})
        current[item_id] = not current.get(item_id, False)
        _save()
        return current[item_id]


def set_checklist_item(user_id: int, item_id: str, done: bool) -> dict[str, bool]:
    """Set a specific item's state. Returns the full checklist dict."""
    with _lock:
        user = _users.get(user_id)
        if not user:
            user = upsert_user(user_id)
        current = user.setdefault("checklist", {})
        current[item_id] = done
        _save()
        return dict(current)


def checklist_progress(user_id: int, all_item_ids: list[str]) -> tuple[int, int]:
    """Return (done_count, total) for the given canonical item list."""
    done_map = get_checklist(user_id)
    total = len(all_item_ids)
    done = sum(1 for iid in all_item_ids if done_map.get(iid))
    return done, total


# ---------- Copy trading checklist (separate from welcome onboarding) ----------

def get_copytrading_checklist(user_id: int) -> dict[str, bool]:
    user = get_user(user_id)
    return user.get("copytrading_checklist", {}) if user else {}


def toggle_copytrading_checklist_item(user_id: int, item_id: str) -> bool:
    with _lock:
        user = _users.get(user_id) or upsert_user(user_id)
        current = user.setdefault("copytrading_checklist", {})
        current[item_id] = not current.get(item_id, False)
        _save()
        return current[item_id]


def reset_copytrading_flow(user_id: int) -> None:
    upsert_user(
        user_id,
        copytrading_checklist={},
        copytrading_completed=False,
        copytrading_platform=None,
    )


def mark_copytrading_completed(user_id: int) -> None:
    upsert_user(
        user_id,
        copytrading_completed=True,
        copytrading_completed_at=datetime.now(timezone.utc).isoformat(),
    )


def is_copytrading_completed(user_id: int) -> bool:
    user = get_user(user_id)
    return bool(user and user.get("copytrading_completed"))


# ---------- Onboarding state ----------

def mark_onboarding_started(user_id: int) -> None:
    upsert_user(
        user_id,
        onboarding_started_at=datetime.now(timezone.utc).isoformat(),
    )


def mark_onboarding_completed(user_id: int) -> None:
    upsert_user(
        user_id,
        onboarding_completed_at=datetime.now(timezone.utc).isoformat(),
        onboarding_completed=True,
    )


def is_onboarding_completed(user_id: int) -> bool:
    user = get_user(user_id)
    return bool(user and user.get("onboarding_completed"))


def is_fully_activated(user_id: int) -> bool:
    """
    True when welcome onboarding is finished (admin-approved or grandfathered).

    Requires admin-approved screenshot (new flow). Users listed in
    TELEGRAM_GRANDFATHER_IDS or with ``grandfathered: true`` skip onboarding
    (buyer's existing members).
    """
    from config import settings

    if user_id in settings.telegram_grandfather_ids:
        return True
    user = get_user(user_id)
    if user and user.get("grandfathered"):
        return True
    return get_approval_status(user_id) == APPROVAL_APPROVED


def needs_onboarding_flow(user_id: int) -> bool:
    return not is_fully_activated(user_id)


# ---------- Manual approval (screenshot review) ----------

APPROVAL_NONE = ""
APPROVAL_AWAITING_SCREENSHOT = "awaiting_screenshot"
APPROVAL_PENDING_REVIEW = "pending_review"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"


def get_approval_status(user_id: int) -> str:
    user = get_user(user_id)
    return (user or {}).get("approval_status") or APPROVAL_NONE


def set_approval_status(user_id: int, status: str, **extra) -> dict:
    return upsert_user(user_id, approval_status=status, **extra)


def is_awaiting_screenshot(user_id: int) -> bool:
    return get_approval_status(user_id) == APPROVAL_AWAITING_SCREENSHOT


def is_pending_review(user_id: int) -> bool:
    return get_approval_status(user_id) == APPROVAL_PENDING_REVIEW


def increment_reminders_sent(user_id: int) -> int:
    """Bump and return the new count."""
    with _lock:
        user = _users.get(user_id) or upsert_user(user_id)
        n = int(user.get("reminders_sent", 0)) + 1
        user["reminders_sent"] = n
        _save()
        return n


# ---------- Whop linking ----------

def link_whop_user(telegram_user_id: int, whop_user_id: str, **extra) -> dict:
    """Bind a Telegram user to a Whop user (reverse-lookup enabled)."""
    with _lock:
        _whop_to_tg[whop_user_id] = telegram_user_id
        user = upsert_user(
            telegram_user_id,
            whop_user_id=whop_user_id,
            **extra,
        )
        _save()
        return user


def get_telegram_id_for_whop_user(whop_user_id: str) -> Optional[int]:
    return _whop_to_tg.get(whop_user_id)


def get_user_by_whop_id(whop_user_id: str) -> Optional[dict]:
    tg_id = _whop_to_tg.get(whop_user_id)
    return _users.get(tg_id) if tg_id else None


# ---------- Pending claims ----------

def add_pending_claim(
    claim_code: str,
    whop_user_id: str,
    whop_membership_id: str,
    product_id: str | None = None,
    **extra,
) -> None:
    """Save a claim code that a user can redeem via /claim <code>."""
    with _lock:
        _pending_claims[claim_code] = {
            "whop_user_id": whop_user_id,
            "whop_membership_id": whop_membership_id,
            "product_id": product_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **extra,
        }
        _save()


def pop_pending_claim(claim_code: str) -> Optional[dict]:
    """Consume a claim code (one-time use)."""
    with _lock:
        claim = _pending_claims.pop(claim_code, None)
        if claim:
            _save()
        return claim


def find_pending_claim_by_whop_user(whop_user_id: str) -> Optional[tuple[str, dict]]:
    """Return (code, claim_data) for the newest pending claim for this Whop user."""
    candidates = [
        (code, data)
        for code, data in _pending_claims.items()
        if data.get("whop_user_id") == whop_user_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda kv: kv[1].get("created_at", ""), reverse=True)
    return candidates[0]


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def find_pending_claim_by_email(email: str) -> Optional[tuple[str, dict]]:
    """Match Whop checkout email to a pending claim (newest first)."""
    target = _normalize_email(email)
    if not target or "@" not in target:
        return None
    candidates = [
        (code, data)
        for code, data in _pending_claims.items()
        if _normalize_email(data.get("email") or "") == target
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda kv: kv[1].get("created_at", ""), reverse=True)
    return candidates[0]
