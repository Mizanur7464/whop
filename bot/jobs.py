"""
Background jobs driven by Telegram's JobQueue.

Currently scheduled:
    * onboarding reminders — N hours after start, ping users who
      haven't finished the checklist (capped by max_reminders)

JobQueue requires the `python-telegram-bot[job-queue]` extra (APScheduler).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from loguru import logger
from telegram.constants import ParseMode
from telegram.ext import Application, ContextTypes

from airtable.client import AirtableClient
from bot import onboarding_config, storage
from config import settings


REMINDER_JOB_PREFIX = "onb_reminder_"
DAILY_REPORT_JOB = "daily_revenue_report"


# ---------- Public API ----------

def schedule_onboarding_reminder(app: Application, telegram_user_id: int) -> None:
    """Schedule the next reminder for a user (idempotent via job name)."""
    if app.job_queue is None:
        logger.warning("JobQueue unavailable — install python-telegram-bot[job-queue]")
        return

    cfg = onboarding_config.get()
    user = storage.get_user(telegram_user_id) or {}
    sent = int(user.get("reminders_sent", 0))

    if sent >= cfg.max_reminders:
        return

    job_name = f"{REMINDER_JOB_PREFIX}{telegram_user_id}_{sent + 1}"

    for existing in app.job_queue.get_jobs_by_name(job_name):
        existing.schedule_removal()

    delay = timedelta(hours=cfg.reminder_hours * (sent + 1))
    app.job_queue.run_once(
        _send_reminder,
        when=delay,
        data={"user_id": telegram_user_id},
        name=job_name,
    )
    logger.info(
        f"Scheduled reminder for user {telegram_user_id} in {delay} (attempt {sent + 1})"
    )


def cancel_user_reminders(app: Application, telegram_user_id: int) -> int:
    """Cancel all pending reminders for a user (used on completion)."""
    if app.job_queue is None:
        return 0
    cancelled = 0
    for job in list(app.job_queue.jobs()):
        if job.name and job.name.startswith(f"{REMINDER_JOB_PREFIX}{telegram_user_id}"):
            job.schedule_removal()
            cancelled += 1
    if cancelled:
        logger.info(f"Cancelled {cancelled} reminders for user {telegram_user_id}")
    return cancelled


# ---------- Job body ----------

async def _send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    user_id = data.get("user_id")
    if not user_id:
        return

    if storage.is_fully_activated(user_id):
        logger.debug(f"Skipping reminder for {user_id} — already completed")
        return

    cfg = onboarding_config.get()
    done_map = storage.get_checklist(user_id)
    total = len(cfg.checklist_items)
    done = sum(1 for item in cfg.checklist_items if done_map.get(item.id))

    if done == total:
        return

    pending = [item.title for item in cfg.checklist_items if not done_map.get(item.id)]
    bullet_list = "\n".join(f"• {title}" for title in pending[:5])
    if len(pending) > 5:
        bullet_list += f"\n• … and {len(pending) - 5} more"

    text = (
        "👋 *Quick reminder*\n\n"
        f"You're {done}/{total} of the way through onboarding. "
        "A few items are still pending:\n\n"
        f"{bullet_list}\n\n"
        "Tap /checklist when you're ready to wrap it up."
    )

    try:
        await context.bot.send_message(
            chat_id=user_id, text=text, parse_mode=ParseMode.MARKDOWN
        )
        new_count = storage.increment_reminders_sent(user_id)
        logger.info(f"Sent reminder #{new_count} to user {user_id}")

        if new_count < cfg.max_reminders:
            schedule_onboarding_reminder(context.application, user_id)
    except Exception as e:
        logger.warning(f"Reminder DM to {user_id} failed: {e}")


# ---------- Daily revenue report ----------

def schedule_daily_report(app: Application, hour_utc: int = 8) -> None:
    """
    Schedule the daily revenue/expense digest at `hour_utc:00` UTC.
    Sent as a DM to every admin in TELEGRAM_ADMIN_IDS.
    """
    if app.job_queue is None:
        logger.warning("JobQueue unavailable — daily report not scheduled")
        return

    for job in app.job_queue.get_jobs_by_name(DAILY_REPORT_JOB):
        job.schedule_removal()

    app.job_queue.run_daily(
        _send_daily_report,
        time=time(hour=hour_utc, minute=0, tzinfo=timezone.utc),
        name=DAILY_REPORT_JOB,
    )
    logger.info(f"Scheduled daily revenue report at {hour_utc:02d}:00 UTC")


async def _send_daily_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not settings.telegram_admin_ids:
        return

    client = AirtableClient()
    if not client.enabled:
        logger.debug("Daily report skipped — Airtable not configured")
        return

    since = datetime.now(timezone.utc) - timedelta(days=1)
    revenue = await client.revenue_summary(since=since)
    expenses = await client.expense_summary(since=since)

    rev_by = revenue.get("by_currency", {})
    exp_by = expenses.get("by_currency", {})
    rev_count = revenue.get("count", 0)
    exp_count = expenses.get("count", 0)

    rev_line = (
        ", ".join(f"{v:,.2f} {c}" for c, v in rev_by.items()) or "0"
    )
    exp_line = (
        ", ".join(f"{v:,.2f} {c}" for c, v in exp_by.items()) or "0"
    )

    body = (
        "📅 *Daily Digest — last 24h*\n\n"
        f"💰 Revenue: *{rev_line}* ({rev_count} payments)\n"
        f"💸 Expenses: *{exp_line}* ({exp_count} entries)\n\n"
        "Run `/pnl 7` for a weekly P&L."
    )

    for admin_id in settings.telegram_admin_ids:
        try:
            await context.bot.send_message(
                chat_id=admin_id, text=body, parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.warning(f"Daily report DM to {admin_id} failed: {e}")
