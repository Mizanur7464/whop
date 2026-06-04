"""
Pre-flight smoke test.

Run this BEFORE the first real deploy to confirm every external service
is reachable with the credentials currently in `.env`. Each check is
independent — a failure on one service won't stop the others.

Usage:
    python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import sys

# Allow `python scripts/smoke_test.py` from project root
sys.path.insert(0, ".")

from loguru import logger

from airtable.client import AirtableClient
from bot import onboarding_config
from config import settings
from integrations.whop_api import WhopAPIError, WhopClient


GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def _ok(label: str, detail: str = "") -> None:
    print(f"{GREEN}✓{RESET}  {label}" + (f"  {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"{RED}✗{RESET}  {label}" + (f"  {detail}" if detail else ""))


def _warn(label: str, detail: str = "") -> None:
    print(f"{YELLOW}!{RESET}  {label}" + (f"  {detail}" if detail else ""))


# ---------- Checks ----------

def check_env() -> bool:
    print("\n── Environment ──")
    ok = True
    required = {
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "WHOP_API_KEY": settings.whop_api_key,
    }
    optional = {
        "WHOP_WEBHOOK_SECRET": settings.whop_webhook_secret,
        "AIRTABLE_API_KEY": settings.airtable_api_key,
        "AIRTABLE_BASE_ID": settings.airtable_base_id,
        "TELEGRAM_MAIN_GROUP_ID": settings.telegram_main_group_id,
    }
    for key, value in required.items():
        if value and "YOUR_" not in str(value):
            _ok(f"{key}", "set")
        else:
            _fail(f"{key}", "missing or placeholder")
            ok = False
    for key, value in optional.items():
        if value and "YOUR_" not in str(value):
            _ok(f"{key}", "set")
        else:
            _warn(f"{key}", "not set (some features will be disabled)")

    if not settings.telegram_admin_ids:
        _warn("TELEGRAM_ADMIN_IDS", "no admins — /stats, /broadcast etc. disabled")
    else:
        _ok("TELEGRAM_ADMIN_IDS", f"{len(settings.telegram_admin_ids)} admin(s)")
    return ok


def check_onboarding_config() -> bool:
    print("\n── Onboarding config ──")
    try:
        cfg = onboarding_config.get()
        _ok(
            "data/onboarding.json",
            f"v{cfg.version}, {len(cfg.checklist_items)} tasks, "
            f"reminder={cfg.reminder_hours}h",
        )
        return True
    except Exception as e:
        _fail("data/onboarding.json", str(e))
        return False


async def check_telegram() -> bool:
    print("\n── Telegram ──")
    try:
        from telegram import Bot

        bot = Bot(token=settings.telegram_bot_token)
        async with bot:
            me = await bot.get_me()
            _ok("Bot token", f"@{me.username} (id={me.id})")
        return True
    except Exception as e:
        _fail("Telegram API", str(e)[:200])
        return False


async def check_whop() -> bool:
    print("\n── Whop API ──")
    if not settings.whop_api_key or "YOUR_" in settings.whop_api_key:
        _warn("Whop API", "key not set — skipping")
        return False
    try:
        async with WhopClient() as client:
            me = await client.get_me()
            _ok("Whop API key", "reachable")
            company = (me or {}).get("title") or (me or {}).get("name") or "—"
            _ok("Company", str(company)[:60])
        return True
    except WhopAPIError as e:
        _fail("Whop API", f"status={e.status} {str(e)[:150]}")
    except Exception as e:
        _fail("Whop API", str(e)[:200])
    return False


async def check_airtable() -> bool:
    print("\n── Airtable ──")
    if not settings.airtable_api_key or not settings.airtable_base_id:
        _warn("Airtable", "key or base ID not set — skipping")
        return False
    client = AirtableClient()
    if not client.enabled:
        _fail("Airtable", "client not initialized")
        return False
    report = await client.validate_schema()
    overall_ok = bool(report.get("all_ok"))
    for key in ("members", "payments", "expenses", "checklist"):
        info = report.get(key, {})
        if info.get("ok"):
            _ok(f"Table '{info.get('table', key)}'", info.get("note") or "schema OK")
        else:
            detail = (
                ", ".join(info.get("missing", []))
                or info.get("error", "unknown")
            )
            _fail(f"Table '{info.get('table', key)}'", detail)
    return overall_ok


# ---------- Entry ----------

async def main() -> int:
    print("┌─────────────────────────────────────────────────────┐")
    print("│  Whop x Telegram x Airtable — Smoke Test            │")
    print("└─────────────────────────────────────────────────────┘")

    results = []
    results.append(("Environment", check_env()))
    results.append(("Onboarding config", check_onboarding_config()))
    results.append(("Telegram", await check_telegram()))
    results.append(("Whop", await check_whop()))
    results.append(("Airtable", await check_airtable()))

    print("\n── Summary ──")
    failed = [name for name, ok in results if not ok]
    if not failed:
        print(f"{GREEN}All checks passed. Ready to deploy.{RESET}\n")
        return 0

    print(f"{RED}Failed: {', '.join(failed)}{RESET}")
    print("\nFix the issues above, then re-run this script.\n")
    return 1


if __name__ == "__main__":
    # Silence loguru INFO during the test
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    try:
        code = asyncio.run(main())
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)
