"""
Whop checkout success page — shows activation code after payment.

Configure in Whop (product → success / redirect URL):
    https://<your-app>/whop/success?membership_id={membership_id}

Whop may pass different query names; the page forwards all query params to
/api/claim/status for lookup.
"""

from __future__ import annotations

import json
import re
from html import escape
from typing import Any
from urllib.parse import urlencode, urlparse

from loguru import logger

from config import settings
from integrations.whop_copy import (
    success_page_heading,
    success_page_invite_heading,
    success_page_invite_hint,
    success_page_preparing,
    success_page_ready_message,
    success_page_still_processing,
    success_page_subtitle,
    success_page_title,
    success_page_wait_hint,
)

SUCCESS_PATH = "/whop/success"
STATUS_PATH = "/api/claim/status"

_PLACEHOLDER_RE = re.compile(r"^\{.+\}$")


def _is_unresolved_whop_placeholder(value: str | None) -> bool:
    """Whop sometimes sends literal `{membership_id}` when the variable is wrong."""
    if not value:
        return False
    v = value.strip()
    return bool(_PLACEHOLDER_RE.match(v)) or v in (
        "{membership_id}",
        "{id}",
        "membership_id",
    )


def normalize_success_query(query: dict[str, str]) -> dict[str, str]:
    """Clean Whop redirect query params and log what we received."""
    out = {k: v for k, v in query.items() if v}
    mid = out.get("membership_id") or out.get("membership") or out.get("id")
    if _is_unresolved_whop_placeholder(mid):
        logger.warning(
            f"success_page: unresolved Whop placeholder membership_id={mid!r} — "
            "fix Redirect URL in Whop (use Whop's real variable, not literal braces). "
            f"other_params={list(k for k in out if k not in ('membership_id',))}"
        )
        for key in ("membership_id", "membership", "id"):
            if out.get(key) and _is_unresolved_whop_placeholder(out.get(key)):
                out.pop(key, None)
    logger.info(f"success_page: query keys={list(out.keys())} membership_id={out.get('membership_id', '—')}")
    return out


def public_app_base_url() -> str:
    """Origin for success page links (no trailing slash)."""
    raw = (getattr(settings, "public_app_base_url", None) or "").strip()
    if raw:
        return raw.rstrip("/")
    webhook = (settings.public_webhook_url or "").strip()
    if webhook:
        parsed = urlparse(webhook)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def telegram_bot_url() -> str:
    username = (settings.telegram_bot_username or "").lstrip("@").strip()
    if username:
        return f"https://t.me/{username}"
    return ""


def telegram_claim_deep_link() -> str:
    username = (settings.telegram_bot_username or "").lstrip("@").strip()
    if username:
        return f"https://t.me/{username}?start=claim"
    return telegram_bot_url()


def _find_pending_claim(
    *,
    membership_id: str | None = None,
    code: str | None = None,
    email: str | None = None,
    receipt_id: str | None = None,
    payment_id: str | None = None,
) -> tuple[str, dict] | None:
    from bot import storage

    found: tuple[str, dict] | None = None
    if membership_id and not _is_unresolved_whop_placeholder(membership_id):
        found = storage.find_pending_claim_by_membership_id(membership_id)
    pay_ref = (payment_id or receipt_id or "").strip()
    if not found and pay_ref:
        found = storage.find_pending_claim_by_payment_id(pay_ref)
    if not found and code:
        found = storage.find_pending_claim_by_code(code.strip().upper())
    if not found and email:
        found = storage.find_pending_claim_by_email(email)
    return found


def lookup_claim_status(
    *,
    membership_id: str | None = None,
    code: str | None = None,
    email: str | None = None,
    receipt_id: str | None = None,
    payment_id: str | None = None,
) -> dict[str, Any]:
    """Sync peek (no invite generation). Prefer lookup_claim_status_async."""
    bot_url = telegram_bot_url()
    claim_link = telegram_claim_deep_link()
    found = _find_pending_claim(
        membership_id=membership_id,
        code=code,
        email=email,
        receipt_id=receipt_id,
        payment_id=payment_id,
    )
    if not found:
        return {
            "ready": False,
            "bot_url": bot_url,
            "claim_url": claim_link,
        }
    claim_code, data = found
    invite_links = data.get("invite_links") if isinstance(data.get("invite_links"), list) else []
    primary = invite_links[0].get("url") if invite_links and isinstance(invite_links[0], dict) else None
    return {
        "ready": True,
        "code": claim_code,
        "plan": data.get("plan") or "membership",
        "bot_url": bot_url,
        "claim_url": claim_link,
        "claim_command": f"/claim {claim_code}",
        "email_hint": data.get("email"),
        "invite_links": invite_links,
        "primary_invite_url": primary,
    }


async def lookup_claim_status_async(
    *,
    membership_id: str | None = None,
    code: str | None = None,
    email: str | None = None,
    receipt_id: str | None = None,
    payment_id: str | None = None,
) -> dict[str, Any]:
    """Poll endpoint: ensures Telegram invite links exist when claim is ready."""
    if _is_unresolved_whop_placeholder(membership_id):
        membership_id = None

    logger.info(
        f"success_page/status: membership_id={membership_id!r} code={code!r} "
        f"email={email!r} receipt_id={receipt_id!r} payment_id={payment_id!r}"
    )

    payload = lookup_claim_status(
        membership_id=membership_id,
        code=code,
        email=email,
        receipt_id=receipt_id,
        payment_id=payment_id,
    )
    if not payload.get("ready"):
        logger.warning(
            "success_page/status: no pending claim yet "
            f"(membership_id={membership_id!r} payment_id={payment_id!r} "
            f"receipt_id={receipt_id!r}) — webhook may still be processing"
        )
        return payload

    found = _find_pending_claim(
        membership_id=membership_id,
        code=code,
        email=email,
        receipt_id=receipt_id,
        payment_id=payment_id,
    )
    if not found:
        return payload

    claim_code, data = found
    logger.info(
        f"success_page/status: found claim code={claim_code} "
        f"membership={data.get('whop_membership_id')} email={data.get('email')}"
    )
    payload["invite_links"] = []
    payload["primary_invite_url"] = None
    logger.info(
        f"success_page/status: ready code={claim_code} "
        f"(invite deferred until onboarding approval)"
    )
    return payload


def render_success_html(query_params: dict[str, str]) -> str:
    """Self-contained success page with polling until webhook creates a claim."""
    query_params = normalize_success_query(query_params)
    qs = urlencode({k: v for k, v in query_params.items() if v})
    status_url = f"{STATUS_PATH}?{qs}" if qs else STATUS_PATH
    bot_url = escape(telegram_bot_url() or "#")
    claim_url = escape(telegram_claim_deep_link() or bot_url)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(success_page_title())}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      margin: 0; min-height: 100vh;
      background: linear-gradient(160deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
      color: #f8fafc; display: flex; align-items: center; justify-content: center;
      padding: 24px;
    }}
    .card {{
      max-width: 420px; width: 100%;
      background: rgba(30, 41, 59, 0.95);
      border: 1px solid rgba(148, 163, 184, 0.2);
      border-radius: 16px; padding: 28px 24px;
      box-shadow: 0 25px 50px rgba(0,0,0,0.35);
      text-align: center;
    }}
    h1 {{ font-size: 1.35rem; margin: 0 0 8px; font-weight: 700; }}
    .sub {{ color: #94a3b8; font-size: 0.95rem; margin-bottom: 24px; line-height: 1.5; }}
    .code-box {{
      background: #0f172a; border: 2px dashed #f59e0b;
      border-radius: 12px; padding: 20px; margin: 16px 0;
      font-size: 1.75rem; font-weight: 800; letter-spacing: 0.2em;
      color: #fbbf24; user-select: all;
    }}
    .hidden {{ display: none; }}
    .spinner {{
      width: 40px; height: 40px; margin: 16px auto;
      border: 3px solid #334155; border-top-color: #f59e0b;
      border-radius: 50%; animation: spin 0.8s linear infinite;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    .btn {{
      display: inline-block; margin-top: 12px; padding: 14px 24px;
      background: #f59e0b; color: #0f172a; font-weight: 700;
      text-decoration: none; border-radius: 10px; font-size: 1rem;
    }}
    .btn:hover {{ background: #fbbf24; }}
    .hint {{ font-size: 0.85rem; color: #94a3b8; margin-top: 16px; line-height: 1.5; }}
    .cmd {{ font-family: ui-monospace, monospace; color: #e2e8f0; }}
    .invite-list {{ text-align: left; margin: 12px 0; }}
    .invite-list a {{
      display: block; margin: 8px 0; padding: 12px 14px;
      background: #0f172a; border-radius: 10px; color: #38bdf8;
      text-decoration: none; font-weight: 600; word-break: break-all;
    }}
    .invite-list a:hover {{ background: #1e293b; }}
    .btn-secondary {{
      display: inline-block; margin-top: 8px; padding: 10px 18px;
      background: transparent; color: #94a3b8; font-weight: 600;
      text-decoration: none; border: 1px solid #475569; border-radius: 10px;
      font-size: 0.9rem;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{escape(success_page_heading())}</h1>
    <p class="sub">{escape(success_page_subtitle())}</p>

    <div id="loading">
      <div class="spinner"></div>
      <p class="sub">{escape(success_page_preparing())}</p>
    </div>

    <div id="ready-invite" class="hidden">
      <p class="sub">{escape(success_page_invite_heading())}</p>
      <div class="invite-list" id="invite-links"></div>
      <a class="btn" id="primary-invite-btn" href="#" target="_blank" rel="noopener">Join main group</a>
      <p class="hint">{escape(success_page_invite_hint())}</p>
      <a class="btn-secondary" id="bot-btn-invite" href="{claim_url}" target="_blank" rel="noopener">Open bot for onboarding</a>
    </div>

    <div id="ready-onboarding" class="hidden">
      <p class="sub">{escape(success_page_ready_message())}</p>
      <a class="btn" id="bot-btn-onboarding" href="{claim_url}" target="_blank" rel="noopener">Open Telegram bot</a>
    </div>

    <div id="ready-code" class="hidden">
      <p class="sub">Your activation code</p>
      <div class="code-box" id="code">--------</div>
      <p class="hint">In Telegram, send <span class="cmd" id="claim-cmd">/claim</span> or tap the button below.</p>
      <a class="btn" id="bot-btn" href="{claim_url}" target="_blank" rel="noopener">Open Telegram bot</a>
    </div>

    <div id="wait" class="hidden">
      <p class="sub">{escape(success_page_still_processing())}</p>
      <a class="btn" href="{claim_url}" target="_blank" rel="noopener">Open Telegram bot</a>
      <p class="hint">{success_page_wait_hint()}</p>
    </div>
  </div>
  <script>
    const statusUrl = {json.dumps(status_url)};
    const pollMs = 2000;
    const maxAttempts = 30;
    let attempts = 0;

    function show(id) {{
      ["loading", "ready-invite", "ready-onboarding", "ready-code", "wait"].forEach(s => {{
        const el = document.getElementById(s);
        if (el) el.classList.toggle("hidden", s !== id);
      }});
    }}

    function renderInvites(data) {{
      const list = document.getElementById("invite-links");
      list.innerHTML = "";
      const links = data.invite_links || [];
      links.forEach((item, i) => {{
        const a = document.createElement("a");
        a.href = item.url;
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = (item.label || ("Group " + (i + 1)));
        list.appendChild(a);
      }});
      const primary = data.primary_invite_url || (links[0] && links[0].url);
      const btn = document.getElementById("primary-invite-btn");
      if (primary) btn.href = primary;
      if (data.claim_url) {{
        const botBtn = document.getElementById("bot-btn-invite");
        if (botBtn) botBtn.href = data.claim_url;
      }}
    }}

    async function poll() {{
      attempts += 1;
      try {{
        const res = await fetch(statusUrl);
        const data = await res.json();
        if (data.ready) {{
          const hasInvite = data.primary_invite_url || (data.invite_links && data.invite_links.length);
          if (hasInvite) {{
            renderInvites(data);
            show("ready-invite");
            return;
          }}
          if (data.claim_url) {{
            const obBtn = document.getElementById("bot-btn-onboarding");
            if (obBtn) obBtn.href = data.claim_url;
          }}
          show("ready-onboarding");
          return;
        }}
      }} catch (e) {{}}
      if (attempts >= maxAttempts) {{
        show("wait");
        return;
      }}
      setTimeout(poll, pollMs);
    }}
    poll();
  </script>
</body>
</html>"""
