"""
Unified entry point.

Runs two concurrent components in one process:
    1. Telegram bot polling (handles user commands)
    2. FastAPI server on :8000 (receives Whop webhooks)

This is what Railway / Render should run as the start command:
    python run.py

For Telegram-only local dev (no webhook), use:
    python -m bot.main
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

import uvicorn
from loguru import logger
from telegram import Update
from telegram.error import NetworkError, TimedOut

from bot.command_registry import register_all_commands
from bot.main import build_app, setup_logging
from config import settings
from integrations import telegram_ops
from integrations.whop_webhook import create_app as create_webhook_app


async def _shutdown_bot(app) -> None:
    try:
        if app.updater.running:
            await app.updater.stop()
    except Exception:
        pass
    try:
        if app.running:
            await app.stop()
    except Exception:
        pass
    try:
        await app.shutdown()
    except Exception:
        pass


async def _run_bot(stop_event: asyncio.Event) -> None:
    """Connect to Telegram with retries (network timeouts are common locally)"""
    delay_sec = 5
    attempt = 0
    while not stop_event.is_set():
        attempt += 1
        app = build_app()
        telegram_ops.set_bot(app)
        try:
            await app.initialize()
            await app.start()
            await register_all_commands(app.bot)
            await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            logger.success("Telegram polling started (slash commands registered)")
            delay_sec = 5
            await stop_event.wait()
            break
        except (TimedOut, NetworkError) as e:
            await _shutdown_bot(app)
            if stop_event.is_set():
                return
            logger.warning(
                f"Cannot reach api.telegram.org (attempt {attempt}): {e}. "
                f"Retrying in {delay_sec}s — check internet/VPN/firewall."
            )
            await asyncio.sleep(delay_sec)
            delay_sec = min(delay_sec * 2, 60)
        except Exception as e:
            await _shutdown_bot(app)
            if stop_event.is_set():
                return
            logger.exception(
                f"Telegram bot crashed (attempt {attempt}): {e}. "
                f"Restarting in {delay_sec}s…"
            )
            await asyncio.sleep(delay_sec)
            delay_sec = min(delay_sec * 2, 60)

    logger.info("Stopping Telegram bot…")
    await _shutdown_bot(app)


def _listen_port() -> int:
    """Railway/Render set PORT; local dev uses WEBHOOK_PORT from .env."""
    raw = os.environ.get("PORT", "").strip()
    if raw:
        return int(raw)
    return settings.webhook_port


async def _run_webhook(stop_event: asyncio.Event) -> None:
    port = _listen_port()
    app = create_webhook_app()
    config = uvicorn.Config(
        app,
        host=settings.webhook_host,
        port=port,
        log_level=settings.log_level.lower(),
        loop="asyncio",
        access_log=True,
    )
    server = uvicorn.Server(config)

    server_task = asyncio.create_task(server.serve())
    logger.success(
        f"Webhook server listening on {settings.webhook_host}:{port}{settings.webhook_path}"
    )

    await stop_event.wait()

    logger.info("Stopping webhook server…")
    server.should_exit = True
    await server_task


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    def handler(*_):
        if not stop_event.is_set():
            logger.info("Shutdown signal received")
            stop_event.set()

    if sys.platform == "win32":
        # On Windows, asyncio doesn't deliver SIGTERM via add_signal_handler.
        # KeyboardInterrupt will still bubble up through asyncio.run().
        signal.signal(signal.SIGINT, handler)
        try:
            signal.signal(signal.SIGTERM, handler)
        except (AttributeError, ValueError):
            pass
        return

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handler)


async def amain() -> None:
    setup_logging()
    logger.info("Booting Whop x Telegram x Airtable (Phase 3 — full stack)")
    logger.info(f"Environment: {settings.environment}")

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    # Start HTTP first so Railway healthcheck (/healthz) passes quickly.
    webhook_task = asyncio.create_task(_run_webhook(stop_event), name="webhook")
    bot_task = asyncio.create_task(_run_bot(stop_event), name="bot")

    await asyncio.gather(webhook_task, bot_task, return_exceptions=True)
    logger.info("All components stopped. Bye!")


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
