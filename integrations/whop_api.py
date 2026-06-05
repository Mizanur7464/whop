"""
Whop REST API client.

Reference: https://dev.whop.com/reference

Auth: Bearer token (the API key from Whop Dashboard > Developer).
Base URL: https://api.whop.com/api/v5

All calls are async via httpx. We expose only the endpoints we actually
need for this project:
    * get_membership(id)        - fetch a single membership
    * list_memberships(...)     - paginated membership listing
    * get_user(id)              - fetch a Whop user
    * get_product(id)           - fetch a product
    * get_me()                  - sanity-check the API key

Errors are wrapped in WhopAPIError so callers don't import httpx.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
from loguru import logger

from config import settings

WHOP_BASE_URL = "https://api.whop.com/api/v5"
DEFAULT_TIMEOUT = 15.0


class WhopAPIError(Exception):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"Whop API {status} on {url}: {body[:300]}")
        self.status = status
        self.body = body
        self.url = url


class WhopClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = WHOP_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key or settings.whop_api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "whop-telegram-bot/0.1",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "WhopClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    # ---------- core ----------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = await self._client.request(method, url, params=params, json=json)
        except httpx.RequestError as e:
            logger.error(f"Whop transport error on {method} {url}: {e}")
            raise WhopAPIError(0, str(e), url) from e

        if resp.status_code >= 400:
            logger.warning(f"Whop {resp.status_code} on {method} {url}: {resp.text[:300]}")
            raise WhopAPIError(resp.status_code, resp.text, url)

        if not resp.content:
            return {}
        return resp.json()

    # ---------- endpoints ----------

    async def get_me(self) -> dict:
        """Sanity check: returns the company tied to this API key."""
        return await self._request("GET", "/company")

    async def get_membership(self, membership_id: str) -> dict:
        return await self._request("GET", f"/company/memberships/{membership_id}")

    async def list_memberships(
        self,
        *,
        valid: bool | None = None,
        product_id: str | None = None,
        per: int = 50,
        page: int = 1,
    ) -> dict:
        params: dict = {"per": per, "page": page}
        if valid is not None:
            params["valid"] = "true" if valid else "false"
        if product_id:
            params["product_id"] = product_id
        return await self._request("GET", "/company/memberships", params=params)

    async def iter_memberships(self, **filters) -> list[dict]:
        """Walk all pages and return a flat list of memberships."""
        results: list[dict] = []
        page = 1
        while True:
            payload = await self.list_memberships(page=page, **filters)
            data = payload.get("data") or []
            results.extend(data)
            pagination = payload.get("pagination") or {}
            total_pages = pagination.get("total_pages") or pagination.get("total_page") or page
            if page >= total_pages:
                break
            page += 1
        return results

    async def get_user(self, user_id: str) -> dict:
        return await self._request("GET", f"/company/users/{user_id}")

    async def get_product(self, product_id: str) -> dict:
        return await self._request("GET", f"/company/products/{product_id}")

    async def terminate_membership(self, membership_id: str) -> dict:
        """Force-end a membership (refund/manual cancel scenarios)."""
        return await self._request("POST", f"/company/memberships/{membership_id}/terminate")
