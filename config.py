"""
Central configuration loader.

Reads all environment variables from .env and exposes them as a
strongly-typed `settings` object. Import from anywhere via:
    from config import settings
"""

from __future__ import annotations

import json
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_id_csv(raw: str) -> List[int]:
    """Parse TELEGRAM_*_IDS from .env: comma-separated or JSON array."""
    s = (raw or "").strip()
    if not s:
        return []
    if s.startswith("["):
        data = json.loads(s)
        return [int(x) for x in data]
    return [int(part.strip()) for part in s.split(",") if part.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Telegram ----
    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_bot_username: str = Field(default="", alias="TELEGRAM_BOT_USERNAME")
    # Community layout: "topics" = one group + forum threads (recommended)
    telegram_community_layout: str = Field(
        default="topics", alias="TELEGRAM_COMMUNITY_LAYOUT"
    )
    telegram_main_group_id: Optional[int] = Field(default=None, alias="TELEGRAM_MAIN_GROUP_ID")
    # Separate entry group: Welcome + Notifications topics (Whop link pinned in Welcome)
    telegram_welcome_group_id: Optional[int] = Field(
        default=None, alias="TELEGRAM_WELCOME_GROUP_ID"
    )
    telegram_welcome_group_topic_welcome: Optional[int] = Field(
        default=None, alias="TELEGRAM_WELCOME_GROUP_TOPIC_WELCOME"
    )
    telegram_welcome_group_topic_notifications: Optional[int] = Field(
        default=None, alias="TELEGRAM_WELCOME_GROUP_TOPIC_NOTIFICATIONS"
    )
    # Forum topic IDs (message_thread_id) inside TELEGRAM_MAIN_GROUP_ID
    telegram_topic_welcome: Optional[int] = Field(
        default=None, alias="TELEGRAM_TOPIC_WELCOME"
    )
    telegram_topic_copytrading: Optional[int] = Field(
        default=None, alias="TELEGRAM_TOPIC_COPYTRADING"
    )
    telegram_topic_offboard: Optional[int] = Field(
        default=None, alias="TELEGRAM_TOPIC_OFFBOARD"
    )
    telegram_topic_support: Optional[int] = Field(
        default=None, alias="TELEGRAM_TOPIC_SUPPORT"
    )
    telegram_topic_signals: Optional[int] = Field(
        default=None, alias="TELEGRAM_TOPIC_SIGNALS"
    )
    telegram_topic_education: Optional[int] = Field(
        default=None, alias="TELEGRAM_TOPIC_EDUCATION"
    )
    telegram_topic_pnl: Optional[int] = Field(
        default=None, alias="TELEGRAM_TOPIC_PNL"
    )
    telegram_topic_notifications: Optional[int] = Field(
        default=None, alias="TELEGRAM_TOPIC_NOTIFICATIONS"
    )
    telegram_vip_group_id: Optional[int] = Field(default=None, alias="TELEGRAM_VIP_GROUP_ID")
    telegram_announcement_channel_id: Optional[int] = Field(
        default=None, alias="TELEGRAM_ANNOUNCEMENT_CHANNEL_ID"
    )
    # Stored as str — pydantic-settings JSON-parses List fields and breaks on "111,222".
    telegram_admin_ids_csv: str = Field(default="", alias="TELEGRAM_ADMIN_IDS")
    telegram_grandfather_ids_csv: str = Field(
        default="", alias="TELEGRAM_GRANDFATHER_IDS"
    )
    telegram_review_admin_ids_csv: str = Field(
        default="", alias="TELEGRAM_REVIEW_ADMIN_IDS"
    )

    # ---- Whop ----
    whop_api_key: str = Field(..., alias="WHOP_API_KEY")
    whop_company_id: str = Field(default="", alias="WHOP_COMPANY_ID")
    whop_webhook_secret: str = Field(default="", alias="WHOP_WEBHOOK_SECRET")
    whop_product_basic: Optional[str] = Field(default=None, alias="WHOP_PRODUCT_BASIC")
    whop_product_premium: Optional[str] = Field(default=None, alias="WHOP_PRODUCT_PREMIUM")
    whop_product_vip: Optional[str] = Field(default=None, alias="WHOP_PRODUCT_VIP")

    # ---- Airtable ----
    airtable_api_key: str = Field(default="", alias="AIRTABLE_API_KEY")
    airtable_base_id: str = Field(default="", alias="AIRTABLE_BASE_ID")
    airtable_members_table: str = Field(default="Members", alias="AIRTABLE_MEMBERS_TABLE")
    airtable_payments_table: str = Field(default="Payments", alias="AIRTABLE_PAYMENTS_TABLE")
    airtable_expenses_table: str = Field(default="Expenses", alias="AIRTABLE_EXPENSES_TABLE")
    airtable_checklist_table: str = Field(default="Checklist", alias="AIRTABLE_CHECKLIST_TABLE")

    # ---- App ----
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    webhook_host: str = Field(default="0.0.0.0", alias="WEBHOOK_HOST")
    webhook_port: int = Field(default=8000, alias="WEBHOOK_PORT")
    webhook_path: str = Field(default="/webhook/whop", alias="WEBHOOK_PATH")
    public_webhook_url: str = Field(default="", alias="PUBLIC_WEBHOOK_URL")
    # Optional: https://your-app.up.railway.app (no path). If empty, derived from PUBLIC_WEBHOOK_URL.
    public_app_base_url: str = Field(default="", alias="PUBLIC_APP_BASE_URL")
    safe_mode: bool = Field(default=True, alias="SAFE_MODE")
    rollout_mode: str = Field(default="new_only", alias="ROLLOUT_MODE")
    group_moderation_enabled: bool = Field(
        default=True, alias="GROUP_MODERATION_DELETE_MEMBER_MESSAGES"
    )
    # Comma-separated forum topic IDs where members may chat (default: education topic).
    group_moderation_member_chat_topics_csv: str = Field(
        default="", alias="GROUP_MODERATION_MEMBER_CHAT_TOPICS"
    )
    welcome_channel_id: Optional[int] = Field(default=None, alias="TELEGRAM_WELCOME_CHANNEL_ID")
    copy_trading_channel_id: Optional[int] = Field(default=None, alias="TELEGRAM_COPYTRADING_CHANNEL_ID")
    offboard_channel_id: Optional[int] = Field(default=None, alias="TELEGRAM_OFFBOARD_CHANNEL_ID")
    support_channel_id: Optional[int] = Field(default=None, alias="TELEGRAM_SUPPORT_CHANNEL_ID")
    signals_channel_id: Optional[int] = Field(default=None, alias="TELEGRAM_SIGNALS_CHANNEL_ID")
    education_channel_id: Optional[int] = Field(default=None, alias="TELEGRAM_EDUCATION_CHANNEL_ID")
    pnl_channel_id: Optional[int] = Field(default=None, alias="TELEGRAM_PNL_CHANNEL_ID")

    # ---- Email (offboard / support forms) ----
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    email_from: str = Field(
        default="info@fusionwealthcapital.com", alias="EMAIL_FROM"
    )
    fusion_email_to: str = Field(
        default="info@fusionwealthcapital.com", alias="FUSION_EMAIL_TO"
    )

    @field_validator(
        "telegram_main_group_id",
        "telegram_welcome_group_id",
        "telegram_welcome_group_topic_welcome",
        "telegram_welcome_group_topic_notifications",
        "telegram_vip_group_id",
        "telegram_announcement_channel_id",
        "welcome_channel_id",
        "copy_trading_channel_id",
        "offboard_channel_id",
        "support_channel_id",
        "signals_channel_id",
        "education_channel_id",
        "pnl_channel_id",
        "telegram_topic_welcome",
        "telegram_topic_copytrading",
        "telegram_topic_offboard",
        "telegram_topic_support",
        "telegram_topic_signals",
        "telegram_topic_education",
        "telegram_topic_pnl",
        "telegram_topic_notifications",
        mode="before",
    )
    @classmethod
    def _parse_optional_chat_id(cls, v):
        """
        Accept blank/placeholder values in .env without crashing.

        Examples accepted:
            TELEGRAM_MAIN_GROUP_ID=          -> None
            TELEGRAM_MAIN_GROUP_ID=-100...   -> int
            TELEGRAM_MAIN_GROUP_ID=-100XXXXXXXXXX -> None (placeholder)
        """
        if v is None:
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            # common placeholder patterns in templates
            if "x" in s.lower() or "your_" in s.lower():
                return None
            try:
                return int(s)
            except ValueError:
                return None
        return None

    @property
    def telegram_admin_ids(self) -> List[int]:
        return _parse_id_csv(self.telegram_admin_ids_csv)

    @property
    def telegram_grandfather_ids(self) -> List[int]:
        return _parse_id_csv(self.telegram_grandfather_ids_csv)

    @property
    def telegram_review_admin_ids(self) -> List[int]:
        return _parse_id_csv(self.telegram_review_admin_ids_csv)

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def onboarding_review_admin_ids(self) -> List[int]:
        """Admins who get screenshot review DMs. Falls back to all admins if unset."""
        if self.telegram_review_admin_ids:
            return self.telegram_review_admin_ids
        return self.telegram_admin_ids


settings = Settings()
