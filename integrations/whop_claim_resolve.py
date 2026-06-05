"""
Resolve a Whop membership for /claim email flow.

1. Local pending_claims (from webhook) — fast path
2. Whop REST API — when webhook was missed (local dev or delivery failure)
"""

from __future__ import annotations

import secrets
from typing import Any

from loguru import logger

from integrations import plan_mapping
from integrations.whop_api import WhopAPIError, WhopClient


def _email_from_membership(m: dict, user: dict | None = None) -> str | None:
    user = user if user is not None else (m.get("user") or {})
    if not isinstance(user, dict):
        user = {}
    for raw in (
        m.get("email"),
        user.get("email"),
        (m.get("member") or {}).get("email") if isinstance(m.get("member"), dict) else None,
    ):
        if isinstance(raw, str) and "@" in raw:
            return raw.strip().lower()
    return None


def _membership_ids(m: dict) -> tuple[str | None, str | None, str | None]:
    whop_user = m.get("user_id") or (m.get("user") or {}).get("id")
    membership_id = m.get("id") or m.get("membership_id")
    product = m.get("product") or {}
    product_id = m.get("product_id") or product.get("id")
    return (
        str(whop_user) if whop_user else None,
        str(membership_id) if membership_id else None,
        str(product_id) if product_id else None,
    )


async def fetch_membership_by_email(email: str) -> dict[str, Any] | None:
    """Query Whop API for a valid membership matching checkout email."""
    target = email.strip().lower()
    if not target or "@" not in target:
        logger.warning("whop_claim_resolve: invalid email input")
        return None

    logger.info(f"whop_claim_resolve: Whop API lookup for email={target!r}")
    try:
        async with WhopClient() as client:
            memberships = await client.iter_memberships(valid=True)
            logger.info(
                f"whop_claim_resolve: fetched {len(memberships)} valid membership(s) from Whop"
            )
            for m in memberships:
                mem_email = _email_from_membership(m)
                whop_user, membership_id, product_id = _membership_ids(m)
                if mem_email == target:
                    logger.info(
                        f"whop_claim_resolve: match membership={membership_id} "
                        f"whop_user={whop_user} product={product_id}"
                    )
                    return {
                        "whop_user_id": whop_user,
                        "whop_membership_id": membership_id,
                        "product_id": product_id,
                        "plan": plan_mapping.resolve_plan_name(product_id),
                        "email": target,
                    }

                if whop_user and not mem_email:
                    try:
                        user_data = await client.get_user(whop_user)
                        u_email = (user_data.get("email") or "").strip().lower()
                        if u_email == target:
                            logger.info(
                                f"whop_claim_resolve: match via get_user "
                                f"membership={membership_id} whop_user={whop_user}"
                            )
                            return {
                                "whop_user_id": whop_user,
                                "whop_membership_id": membership_id,
                                "product_id": product_id,
                                "plan": plan_mapping.resolve_plan_name(product_id),
                                "email": target,
                            }
                    except WhopAPIError as e:
                        logger.warning(
                            f"whop_claim_resolve: get_user({whop_user}) failed: {e.status}"
                        )
    except WhopAPIError as e:
        logger.error(f"whop_claim_resolve: Whop API error status={e.status}")
        return None
    except Exception as e:
        logger.opt(exception=e).error("whop_claim_resolve: unexpected error")
        return None

    logger.warning(f"whop_claim_resolve: no Whop membership for email={target!r}")
    return None


def new_claim_code() -> str:
    return secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].upper()
