"""
Whop checkout success page — shows activation code after payment.

Configure in Whop (product → success / redirect URL):
    https://<your-app>/whop/success?membership_id={membership_id}

Whop may pass different query names; the page forwards all query params to
/api/claim/status for lookup.
"""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlencode, urlparse

from config import settings

SUCCESS_PATH = "/whop/success"
STATUS_PATH = "/api/claim/status"


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


def lookup_claim_status(
    *,
    membership_id: str | None = None,
    code: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    from bot import storage

    found: tuple[str, dict] | None = None

    if membership_id:
        found = storage.find_pending_claim_by_membership_id(membership_id)
    if not found and code:
        found = storage.find_pending_claim_by_code(code.strip().upper())
    if not found and email:
        found = storage.find_pending_claim_by_email(email)

    bot_url = telegram_bot_url()
    claim_link = telegram_claim_deep_link()

    if not found:
        return {
            "ready": False,
            "bot_url": bot_url,
            "claim_url": claim_link,
        }

    claim_code, data = found
    return {
        "ready": True,
        "code": claim_code,
        "plan": data.get("plan") or "membership",
        "bot_url": bot_url,
        "claim_url": claim_link,
        "claim_command": f"/claim {claim_code}",
        "email_hint": data.get("email"),
    }


def render_success_html(query_params: dict[str, str]) -> str:
    """Self-contained success page with polling until webhook creates a claim."""
    qs = urlencode({k: v for k, v in query_params.items() if v})
    status_url = f"{STATUS_PATH}?{qs}" if qs else STATUS_PATH
    bot_url = escape(telegram_bot_url() or "#")
    claim_url = escape(telegram_claim_deep_link() or bot_url)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Payment successful — Fusion Strategy</title>
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
  </style>
</head>
<body>
  <div class="card">
    <h1>Payment successful</h1>
    <p class="sub">Thank you for joining Fusion Strategy. Use the steps below to open Telegram access.</p>

    <div id="loading">
      <div class="spinner"></div>
      <p class="sub">Preparing your activation code…</p>
    </div>

    <div id="ready" class="hidden">
      <p class="sub">Your activation code</p>
      <div class="code-box" id="code">--------</div>
      <p class="hint">In Telegram, send <span class="cmd" id="claim-cmd">/claim</span> or tap the button below.</p>
      <a class="btn" id="bot-btn" href="{claim_url}" target="_blank" rel="noopener">Open Telegram bot</a>
    </div>

    <div id="wait" class="hidden">
      <p class="sub">Still processing your payment.</p>
      <a class="btn" href="{claim_url}" target="_blank" rel="noopener">Open Telegram bot</a>
      <p class="hint">Send <span class="cmd">/claim</span> in the bot, then reply with the <strong>email</strong> you used on Whop.</p>
    </div>
  </div>
  <script>
    const statusUrl = {json.dumps(status_url)};
    const pollMs = 2000;
    const maxAttempts = 30;
    let attempts = 0;

    function show(id) {{
      ["loading", "ready", "wait"].forEach(s => {{
        document.getElementById(s).classList.toggle("hidden", s !== id);
      }});
    }}

    async function poll() {{
      attempts += 1;
      try {{
        const res = await fetch(statusUrl);
        const data = await res.json();
        if (data.ready && data.code) {{
          document.getElementById("code").textContent = data.code;
          document.getElementById("claim-cmd").textContent = data.claim_command || ("/claim " + data.code);
          if (data.claim_url) document.getElementById("bot-btn").href = data.claim_url;
          show("ready");
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
