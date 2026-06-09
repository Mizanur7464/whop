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


def _product_name_from_membership(m: dict) -> str | None:
    product = m.get("product") or {}
    if not isinstance(product, dict):
        return None
    return product.get("title") or product.get("name")


def _claim_payload(
    *,
    whop_user: str | None,
    membership_id: str | None,
    product_id: str | None,
    email: str,
    product_name: str | None = None,
) -> dict[str, Any]:
    return {
        "whop_user_id": whop_user,
        "whop_membership_id": membership_id,
        "product_id": product_id,
        "product_name": product_name,
        "plan": plan_mapping.resolve_plan_name(product_id, product_name),
        "email": email,
    }


async def _match_membership_row(
    client: WhopClient, m: dict, target: str
) -> dict[str, Any] | None:
    mem_email = _email_from_membership(m)
    whop_user, membership_id, product_id = _membership_ids(m)
    product_name = _product_name_from_membership(m)
    if mem_email == target:
        logger.info(
            f"whop_claim_resolve: match membership={membership_id} "
            f"whop_user={whop_user} product={product_id}"
        )
        return _claim_payload(
            whop_user=whop_user,
            membership_id=membership_id,
            product_id=product_id,
            email=target,
            product_name=product_name,
        )

    if whop_user and not mem_email:
        try:
            user_data = await client.get_user(whop_user)
            u_email = (user_data.get("email") or "").strip().lower()
            if u_email == target:
                logger.info(
                    f"whop_claim_resolve: match via get_user "
                    f"membership={membership_id} whop_user={whop_user}"
                )
                return _claim_payload(
                    whop_user=whop_user,
                    membership_id=membership_id,
                    product_id=product_id,
                    email=target,
                    product_name=product_name,
                )
        except WhopAPIError as e:
            logger.warning(
                f"whop_claim_resolve: get_user({whop_user}) failed: {e.status}"
            )
    return None


async def fetch_membership_by_email(email: str) -> dict[str, Any] | None:
    """Query Whop API for a valid membership matching checkout email."""
    target = email.strip().lower()
    if not target or "@" not in target:
        logger.warning("whop_claim_resolve: invalid email input")
        return None

    logger.info(f"whop_claim_resolve: Whop API lookup for email={target!r}")
    try:
        async with WhopClient() as client:
            page = 1
            while True:
                payload = await client.list_memberships(valid=True, page=page, per=50)
                data = payload.get("data") or []
                for m in data:
                    matched = await _match_membership_row(client, m, target)
                    if matched:
                        return matched

                pagination = payload.get("pagination") or {}
                total_pages = (
                    pagination.get("total_pages")
                    or pagination.get("total_page")
                    or page
                )
                if page >= total_pages or not data:
                    break
                page += 1
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
