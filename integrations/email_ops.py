"""
Send form submissions to Fusion Wealth inbox via SMTP.

Configure in .env:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
    EMAIL_FROM, FUSION_EMAIL_TO (default info@fusionwealthcapital.com)

If SMTP is not configured, submissions are logged to logs/form_submissions.json
and admins are notified via Telegram when possible.
"""

from __future__ import annotations

import json
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from loguru import logger

from config import settings

_LOG_PATH = Path("logs/form_submissions.json")


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def _append_log(entry: dict[str, Any]) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    if _LOG_PATH.exists():
        try:
            rows = json.loads(_LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            rows = []
    rows.append(entry)
    _LOG_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def send_form_email(
    *,
    subject: str,
    body: str,
    form_type: str,
    telegram_user_id: int,
) -> bool:
    """
    Send email to FUSION_EMAIL_TO. Returns True if sent (or logged in dev).
    """
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "form_type": form_type,
        "telegram_user_id": telegram_user_id,
        "subject": subject,
        "body": body,
    }

    if not _smtp_configured():
        logger.warning(
            "SMTP not configured — saving submission to logs/form_submissions.json"
        )
        _append_log(entry)
        return False

    msg = MIMEMultipart()
    msg["From"] = settings.email_from
    msg["To"] = settings.fusion_email_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(
                settings.email_from,
                [settings.fusion_email_to],
                msg.as_string(),
            )
        logger.info(f"Email sent: {subject} -> {settings.fusion_email_to}")
        _append_log({**entry, "email_sent": True})
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        _append_log({**entry, "email_sent": False, "error": str(e)})
        return False
