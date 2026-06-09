"""
Map Whop product/plan IDs to Telegram chats.

The buyer's setup may look like:
    Basic   -> main group
    Premium -> main group + announcements channel
    VIP     -> main group + announcements + VIP-only group

Edit `_MAPPING` once the buyer confirms their plan structure.
Until then the resolver falls back to the main group for any plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from loguru import logger

from config import settings


@dataclass(frozen=True)
class PlanTier:
    name: str
    whop_product_id: str | None
    chats: tuple[int, ...]


def _build_mapping() -> dict[str, PlanTier]:
    """Build the registry from environment-configured product IDs."""
    main = settings.telegram_main_group_id
    vip = settings.telegram_vip_group_id
    ann = settings.telegram_announcement_channel_id

    tiers: dict[str, PlanTier] = {}

    if settings.whop_product_basic:
        tiers[settings.whop_product_basic] = PlanTier(
            name="basic",
            whop_product_id=settings.whop_product_basic,
            chats=tuple(c for c in [main] if c),
        )
    if settings.whop_product_premium:
        tiers[settings.whop_product_premium] = PlanTier(
            name="premium",
            whop_product_id=settings.whop_product_premium,
            chats=tuple(c for c in [main, ann] if c),
        )
    if settings.whop_product_vip:
        tiers[settings.whop_product_vip] = PlanTier(
            name="vip",
            whop_product_id=settings.whop_product_vip,
            chats=tuple(c for c in [main, ann, vip] if c),
        )

    return tiers


_MAPPING: dict[str, PlanTier] = _build_mapping()

_FALLBACK = PlanTier(
    name="unknown",
    whop_product_id=None,
    chats=tuple(c for c in [settings.telegram_main_group_id] if c),
)


def resolve_chats_for_product(product_id: str | None) -> tuple[int, ...]:
    """Return the chats a user should be granted access to for a given product."""
    if not product_id:
        logger.debug("plan_mapping: no product_id, using fallback")
        return _FALLBACK.chats

    tier = _MAPPING.get(product_id)
    if tier is None:
        logger.warning(
            f"plan_mapping: unknown product {product_id}, falling back to main group"
        )
        return _FALLBACK.chats
    return tier.chats


def resolve_plan_name(
    product_id: str | None,
    product_label: str | None = None,
) -> str:
    if product_id:
        tier = _MAPPING.get(product_id)
        if tier:
            return tier.name
    if product_label:
        label = product_label.strip()
        if label:
            return label
    return "unknown"


def plan_for_airtable(plan: str | None) -> str | None:
    """Format plan for Airtable — always persist something when we have a value."""
    if not plan or not plan.strip():
        return None
    normalized = plan.strip().lower()
    if normalized == "unknown":
        return "unknown"
    if normalized in {"basic", "premium", "vip"}:
        return normalized.title()
    return plan.strip()[:80]


def all_known_chats() -> set[int]:
    """Union of every chat referenced anywhere in the mapping."""
    chats: set[int] = set()
    for tier in _MAPPING.values():
        chats.update(tier.chats)
    chats.update(_FALLBACK.chats)
    return chats


def iter_tiers() -> Iterable[PlanTier]:
    return _MAPPING.values()
