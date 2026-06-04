"""Route text messages to support form collector."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.channel_context import is_private_chat
from bot.handlers import claim, leave_survey, onboarding, support_channel


async def on_form_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_private_chat(update):
        return
    if claim.whop_email_activation_active(update, context):
        await claim.on_whop_email_text(update, context)
        return
    if leave_survey.leave_reason_active(update, context):
        await leave_survey.on_leave_reason_text(update, context)
        return
    if onboarding.onboarding_contact_active(update, context):
        await onboarding.on_onboarding_contact_text(update, context)
        return
    if support_channel.support_form_active(update, context):
        await support_channel.on_form_text(update, context)
