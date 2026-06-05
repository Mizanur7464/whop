"""
Generate and persist Telegram invite links for the Whop success page.
"""

from __future__ import annotations

from loguru import logger

from bot import storage
from config import settings
from integrations import plan_mapping, telegram_ops

# Success page always shows the main premium group only (not VIP/announcements).
INVITE_SCOPE_MAIN = "main_group"


def _valid_invite_links(links: object) -> list[dict[str, str]]:
    if not isinstance(links, list):
        return []
    out: list[dict[str, str]] = []
    for item in links:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if isinstance(url, str) and url.startswith("https://t.me/"):
            out.append(
                {
                    "label": str(item.get("label") or "Telegram group"),
                    "url": url,
                }
            )
    return out


def main_group_chat_ids() -> tuple[int, ...]:
    """Telegram chat IDs shown on the Whop success page."""
    gid = settings.telegram_main_group_id
    return (gid,) if gid else ()


async def ensure_pending_claim_invite_links(
    claim_code: str,
    claim: dict,
) -> list[dict[str, str]]:
    """
    Return invite links for a pending claim, generating and saving if missing.
    """
    existing = _valid_invite_links(claim.get("invite_links"))
    if existing and claim.get("invite_scope") == INVITE_SCOPE_MAIN:
        return existing

    product_id = claim.get("product_id")
    plan_name = claim.get("plan") or plan_mapping.resolve_plan_name(product_id)
    chats = main_group_chat_ids()
    if not chats:
        logger.warning(
            f"success_invites: TELEGRAM_MAIN_GROUP_ID not set — cannot build success page link"
        )
        return []

    try:
        links = await telegram_ops.build_invite_link_list(chats, plan_name=plan_name)
    except RuntimeError as e:
        logger.warning(f"success_invites: bot not ready for {claim_code}: {e}")
        return []

    if links:
        storage.update_pending_claim(
            claim_code,
            invite_links=links,
            invite_scope=INVITE_SCOPE_MAIN,
        )
        logger.info(
            f"success_invites: main group invite stored for claim {claim_code}"
        )
    return links
