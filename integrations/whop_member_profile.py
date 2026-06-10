"""Extract member profile fields from Whop membership API payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WhopMemberProfile:
    email: str | None = None
    name: str | None = None
    phone: str | None = None
    join_date: str | None = None


def _first_str(*values: Any) -> str | None:
    for raw in values:
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def profile_from_membership(m: dict) -> WhopMemberProfile:
    user = m.get("user") if isinstance(m.get("user"), dict) else {}
    billing = m.get("billing") if isinstance(m.get("billing"), dict) else {}
    customer = m.get("customer") if isinstance(m.get("customer"), dict) else {}
    member = m.get("member") if isinstance(m.get("member"), dict) else {}

    email = _first_str(
        m.get("email"),
        user.get("email"),
        m.get("user_email"),
        billing.get("email"),
        customer.get("email"),
        member.get("email"),
    )
    if email:
        email = email.lower()

    name = _first_str(
        user.get("name"),
        m.get("name"),
        customer.get("name"),
        member.get("name"),
    )
    if not name:
        parts = [
            _first_str(user.get("first_name"), customer.get("first_name")),
            _first_str(user.get("last_name"), customer.get("last_name")),
        ]
        name = " ".join(p for p in parts if p) or None

    phone = _first_str(
        user.get("phone"),
        user.get("phone_number"),
        m.get("phone"),
        billing.get("phone"),
        customer.get("phone"),
        member.get("phone"),
    )

    join_date = _first_str(
        m.get("created_at"),
        m.get("valid_at"),
        m.get("joined_at"),
    )

    return WhopMemberProfile(
        email=email,
        name=name,
        phone=phone,
        join_date=join_date,
    )
