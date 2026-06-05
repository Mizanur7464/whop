"""
FastAPI webhook receiver for Whop events.

Endpoints:
    GET  /             - health check (Railway pings this)
    POST /webhook/whop - signature-verified event ingestion

Signature scheme (Whop):
    HMAC-SHA256 over the raw request body, keyed by the webhook secret.
    Whop sends the hex digest in the `Whop-Signature` header.
    We compare in constant time. If WHOP_WEBHOOK_SECRET is unset
    (dev mode), verification is skipped and a warning is logged.

The endpoint always returns 200 OK quickly so Whop doesn't retry while
we're still processing — the actual work is dispatched to a background
task in whop_events.dispatch_event().
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from loguru import logger

from config import settings
from integrations import whop_events
from integrations.whop_success_page import (
    SUCCESS_PATH,
    STATUS_PATH,
    lookup_claim_status_async,
    render_success_html,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Whop Webhook Receiver",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def log_http_requests(request: Request, call_next):
        path = request.url.path
        if path.startswith(("/whop/", "/api/claim/", settings.webhook_path)):
            qs = dict(request.query_params)
            logger.info(f"HTTP {request.method} {path} query={qs}")
        try:
            response = await call_next(request)
            if path.startswith(("/whop/", "/api/claim/")):
                logger.info(f"HTTP {request.method} {path} -> {response.status_code}")
            return response
        except Exception as e:
            logger.exception(f"HTTP 500 {request.method} {path}: {e}")
            raise

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> PlainTextResponse:
        logger.exception(
            f"Unhandled error on {request.method} {request.url.path}: {exc}"
        )
        return PlainTextResponse("Internal Server Error", status_code=500)

    @app.get("/")
    async def health() -> dict:
        return {"status": "ok", "service": "whop-webhook"}

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.post(settings.webhook_path)
    async def whop_webhook(
        request: Request,
        background: BackgroundTasks,
        whop_signature: str | None = Header(default=None, alias="Whop-Signature"),
    ) -> JSONResponse:
        raw_body = await request.body()

        if not _verify_signature(raw_body, whop_signature):
            logger.warning(
                "Webhook signature verification FAILED — check WHOP_WEBHOOK_SECRET matches Whop dashboard"
            )
            raise HTTPException(status_code=401, detail="invalid signature")

        try:
            payload: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as e:
            logger.warning(f"Webhook bad JSON: {e}")
            raise HTTPException(status_code=400, detail="invalid json") from e

        event_type = payload.get("event") or payload.get("action") or "unknown"
        event_id = payload.get("id") or payload.get("event_id") or "—"
        entity = (
            payload.get("data")
            or payload.get("membership")
            or payload.get("payment")
            or {}
        )
        user_block = entity.get("user") if isinstance(entity.get("user"), dict) else {}
        email_hint = (
            entity.get("email")
            or user_block.get("email")
            or "—"
        )
        logger.info(
            f"Webhook received: {event_type} (id={event_id}) email={email_hint}"
        )

        # Fire-and-forget: respond fast, process async.
        background.add_task(whop_events.dispatch_event, payload)

        return JSONResponse({"received": True, "event": event_type})

    @app.get(SUCCESS_PATH, response_class=HTMLResponse)
    async def whop_success_page(request: Request) -> HTMLResponse:
        """Buyer redirect target after Whop checkout."""
        params = {k: v for k, v in request.query_params.items() if v}
        logger.info(f"success_page: GET {SUCCESS_PATH} params={params}")
        try:
            html = render_success_html(params)
        except Exception as e:
            logger.exception(f"success_page: render failed: {e}")
            raise
        logger.success(f"success_page: rendered OK ({len(html)} bytes)")
        return HTMLResponse(html)

    @app.get(STATUS_PATH)
    async def claim_status(
        membership_id: str | None = Query(default=None),
        membership: str | None = Query(default=None),
        id: str | None = Query(default=None),
        code: str | None = Query(default=None),
        email: str | None = Query(default=None),
        receipt_id: str | None = Query(default=None),
        payment_id: str | None = Query(default=None),
    ) -> JSONResponse:
        """Poll until webhook has created a pending claim."""
        mid = membership_id or membership or id
        payload = await lookup_claim_status_async(
            membership_id=mid,
            code=code,
            email=email,
            receipt_id=receipt_id,
            payment_id=payment_id,
        )
        return JSONResponse(payload)

    return app


def _verify_signature(body: bytes, signature: str | None) -> bool:
    """Constant-time HMAC-SHA256 check against the configured secret."""
    secret = settings.whop_webhook_secret
    if not secret:
        logger.warning(
            "WHOP_WEBHOOK_SECRET not set — accepting webhooks without verification. "
            "DO NOT run like this in production."
        )
        return True
    if not signature:
        return False

    # Whop may send the signature as plain hex or as "sha256=<hex>"
    if signature.startswith("sha256="):
        signature = signature.split("=", 1)[1]

    expected = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
