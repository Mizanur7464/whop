"""
Onboarding flow:
    Welcome -> Location -> PDF -> Checklist -> Confirm ->
    Terms PDF + Accept -> Screenshot -> Admin approve -> Unlock.

Callback prefixes:
    onb:welcome, onb:continue_intro, onb:show_location, onb:loc:<id>
    onb:continue, onb:confirm_ready
    onb:approve:<telegram_user_id>, onb:reject:<telegram_user_id>
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from airtable import sync as airtable_sync
from bot.community_unlock import unlock_for_user
from bot import jobs, keyboards, onboarding_config, storage
from bot.decorators import log_call
from bot.channel_context import block_if_group_chat, ensure_welcome_context
from bot.main_group_access import needs_claim_only_menu
from integrations.whop_copy import join_main_before_onboarding_hint
from bot.community_layout import FLOW_WELCOME
from bot.messaging import send_document, send_text
from bot.telegram_utils import safe_answer_callback
from bot import terms_config
from bot.welcome_docs import location_by_id, get as get_welcome_docs

CONTACT_STEP_KEY = "onboarding_contact_step"


def onboarding_contact_active(_: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return context.user_data.get(CONTACT_STEP_KEY) in ("email", "phone")


def _onb_action(data: str) -> str:
    """Return the part after ``onb:`` (supports values like ``loc:uae``)."""
    return data[4:] if data.startswith("onb:") else ""


def _msg(template: str, **kwargs: str) -> str:
    """Format a config message if it contains placeholders."""
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except KeyError:
        return template


async def _send_or_edit(
    update: Update, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    parse_kwargs = dict(
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=markup, **parse_kwargs
            )
        except BadRequest as e:
            err = str(e).lower()
            if "not modified" in err:
                return
            # Stale inline buttons / edit failed — send a fresh message instead.
            logger.warning(f"edit_message failed ({e}); sending new message")
            await update.callback_query.message.reply_text(
                text, reply_markup=markup, **parse_kwargs
            )
    else:
        await update.effective_message.reply_text(
            text, reply_markup=markup, **parse_kwargs
        )


async def _send_new_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    flow: str | None = FLOW_WELCOME,
) -> None:
    """Always post a new message (avoids stale inline keyboard callbacks)."""
    await send_text(update, context, text, markup=markup, flow=flow)


# ---------- Screens ----------

async def show_welcome(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Step 1: Nice welcome message only."""
    cfg = onboarding_config.get()
    user = update.effective_user
    storage.mark_onboarding_started(user.id)

    text = _msg(cfg.welcome_message)
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(cfg.btn_next, callback_data="onb:show_location")]]
    )
    await _send_or_edit(update, text, markup)


async def show_location(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Step 2: Location selection (doc: Inside UAE / outside UAE)."""
    cfg = onboarding_config.get()
    text = _msg(cfg.location_message)
    rows = [
        [InlineKeyboardButton(loc.label, callback_data=f"onb:loc:{loc.id}")]
        for loc in get_welcome_docs().locations
    ]
    if not rows:
        logger.error("welcome_docs.json has no locations configured")
        await _send_or_edit(
            update,
            "Location options are not configured yet. Please contact support.",
            None,
        )
        return
    markup = InlineKeyboardMarkup(rows)
    # New message so the Continue button cannot reuse a stale callback.
    await _send_new_message(update, context, text, markup)


async def _send_location_doc(
    update: Update, context: ContextTypes.DEFAULT_TYPE, location_id: str
) -> None:
    """Step 4: Send PDF only after location is chosen."""
    loc = location_by_id(location_id)
    if not loc:
        await update.callback_query.answer("Invalid selection.", show_alert=True)
        return

    user = update.effective_user
    storage.upsert_user(user.id, location=loc.id, platform=loc.platform)

    if loc.doc.type == "url" and loc.doc.url:
        await send_text(
            update,
            context,
            f"{loc.doc.caption}\n\n{loc.doc.url}",
            flow=FLOW_WELCOME,
            disable_preview=False,
        )
    elif loc.doc.type == "file" and loc.doc.path:
        try:
            with open(loc.doc.path, "rb") as f:
                await send_document(
                    update,
                    context,
                    f,
                    caption=loc.doc.caption or f"{loc.platform} onboarding instructions",
                    flow=FLOW_WELCOME,
                )
        except FileNotFoundError:
            await send_text(
                update,
                context,
                "Onboarding document is not uploaded yet. The team will add it shortly.",
                flow=FLOW_WELCOME,
            )

    await update.callback_query.answer("Document sent ✅")


def _all_checklist_done(user_id: int) -> bool:
    cfg = onboarding_config.get()
    done_map = storage.get_checklist(user_id)
    return all(done_map.get(item.id) for item in cfg.checklist_items)


async def show_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Step 5: Checklist after PDF."""
    cfg = onboarding_config.get()
    user = update.effective_user
    done_map = storage.get_checklist(user.id)

    items_render = [
        {"id": item.id, "title": item.title, "done": done_map.get(item.id, False)}
        for item in cfg.checklist_items
    ]

    done = sum(1 for it in items_render if it["done"])
    total = len(items_render)
    bar = _progress_bar(done, total)

    text = (
        f"{cfg.checklist_intro}\n\n"
        f"Progress: {done}/{total}  {bar}"
    )

    markup = keyboards.checklist_keyboard(
        items_render,
        onboarding=True,
        continue_label=cfg.btn_continue,
    )

    # After location + PDF, send checklist as a fresh message if we just sent a doc
    if update.callback_query and update.callback_query.data.startswith("onb:loc:"):
        await send_text(update, context, text, markup=markup, flow=FLOW_WELCOME)
    else:
        await _send_or_edit(update, text, markup)


async def show_continue(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _all_checklist_done(user.id):
        await update.callback_query.answer(
            "Please complete all checklist steps first.", show_alert=True
        )
        return

    cfg = onboarding_config.get()
    text = _msg(cfg.confirmation_warning_message)
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    cfg.btn_everything_set_up, callback_data="onb:confirm_ready"
                )
            ]
        ]
    )
    await _send_or_edit(update, text, markup)


async def show_terms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Step before screenshot: T&C PDF + Accept."""
    user = update.effective_user
    if not _all_checklist_done(user.id):
        await update.callback_query.answer(
            "Please complete all checklist steps first.", show_alert=True
        )
        return

    tcfg = terms_config.get()
    doc = tcfg.doc
    if doc.type == "file" and doc.path:
        try:
            with open(doc.path, "rb") as f:
                await send_document(
                    update,
                    context,
                    f,
                    caption=doc.caption or "Terms & Disclaimer",
                    flow=FLOW_WELCOME,
                )
        except FileNotFoundError:
            await send_text(
                update,
                context,
                "Terms document is not uploaded yet. Please contact support.",
                flow=FLOW_WELCOME,
            )
    elif doc.type == "url" and doc.url:
        await send_text(
            update,
            context,
            f"{doc.caption or 'Terms'}\n\n{doc.url}",
            flow=FLOW_WELCOME,
            disable_preview=False,
        )

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    tcfg.btn_accept, callback_data="onb:accept_terms"
                )
            ]
        ]
    )
    await send_text(update, context, tcfg.message, markup=markup, flow=FLOW_WELCOME)


async def accept_terms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User accepted T&C — log, notify admins, then ask for screenshot."""
    user = update.effective_user
    if not _all_checklist_done(user.id):
        await update.callback_query.answer(
            "Please complete all checklist steps first.", show_alert=True
        )
        return

    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_user(
        user.id,
        terms_accepted_at=now,
        terms_accepted=True,
        approval_status=storage.APPROVAL_AWAITING_SCREENSHOT,
    )

    name = " ".join(p for p in [user.first_name, user.last_name] if p) or None
    await airtable_sync.terms_accepted(
        telegram_user_id=user.id,
        telegram_username=user.username,
        name=name,
        accepted_at_iso=now,
    )
    await _notify_admins_terms_accepted(context, user, now)

    cfg = onboarding_config.get()
    await update.callback_query.answer("Accepted ✅")
    await _send_new_message(update, context, cfg.screenshot_request_message, None)


async def show_contact_intro(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Collect email, phone, and confirm Telegram ID before T&C."""
    user = update.effective_user
    record = storage.get_user(user.id) or {}
    if record.get("contact_email") and record.get("contact_phone"):
        await show_terms(update, context)
        return

    cfg = onboarding_config.get()
    uname = (
        f"@{user.username}"
        if user.username
        else "_not set — please set a username in Telegram_"
    )
    text = (
        _msg(
            cfg.contact_intro_message,
            telegram_id=str(user.id),
            telegram_username=uname,
        )
        + "\n\n"
        + cfg.contact_email_prompt
    )
    context.user_data[CONTACT_STEP_KEY] = "email"
    if update.callback_query:
        await update.callback_query.answer()
    await _send_new_message(update, context, text, None)


async def on_onboarding_contact_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not onboarding_contact_active(update, context):
        return
    user = update.effective_user
    if not user or not update.message:
        return

    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Please send a valid answer.")
        return

    cfg = onboarding_config.get()
    step = context.user_data.get(CONTACT_STEP_KEY)

    if step == "email":
        if "@" not in text or len(text) < 5:
            await update.message.reply_text("Please send a valid email address.")
            return
        storage.upsert_user(
            user.id,
            contact_email=text,
            contact_telegram_id=user.id,
            telegram_username=user.username,
        )
        context.user_data[CONTACT_STEP_KEY] = "phone"
        await update.message.reply_text(
            cfg.contact_phone_prompt, parse_mode=ParseMode.MARKDOWN
        )
        return

    if step == "phone":
        storage.upsert_user(
            user.id,
            contact_phone=text,
            contact_telegram_id=user.id,
            telegram_username=user.username,
        )
        context.user_data.pop(CONTACT_STEP_KEY, None)
        record = storage.get_user(user.id) or {}
        await airtable_sync.member_contact_collected(
            telegram_user_id=user.id,
            telegram_username=user.username,
            name=user.full_name,
            email=record.get("contact_email", text),
            phone=text,
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        cfg.btn_continue, callback_data="onb:contact_done"
                    )
                ]
            ]
        )
        await update.message.reply_text(
            cfg.contact_saved_message,
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN,
        )


async def confirm_ready(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """After checklist — contact details, then terms."""
    await show_contact_intro(update, context)


async def contact_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_terms(update, context)


@log_call
async def on_screenshot_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Receive account-link screenshot for manual admin approval."""
    if await block_if_group_chat(
        update, context, flow=FLOW_WELCOME, command="start"
    ):
        return

    user = update.effective_user
    if not user or not update.message or not update.message.photo:
        return

    if storage.is_fully_activated(user.id):
        cfg = onboarding_config.get()
        await update.message.reply_text(cfg.idle_after_complete_message)
        return

    status = storage.get_approval_status(user.id)
    if status == storage.APPROVAL_PENDING_REVIEW:
        await update.message.reply_text(
            "Your screenshot is already with our team for review. "
            "We'll message you once it's approved."
        )
        return

    record = storage.get_user(user.id) or {}
    if not record.get("terms_accepted_at"):
        await update.message.reply_text(
            "Please accept the terms and conditions first "
            "(use /onboarding and complete all steps)."
        )
        return

    if status not in (
        storage.APPROVAL_AWAITING_SCREENSHOT,
        storage.APPROVAL_REJECTED,
    ):
        await update.message.reply_text(
            "Please complete the onboarding steps first. Send /start to begin."
        )
        return

    file_id = update.message.photo[-1].file_id
    storage.set_approval_status(
        user.id,
        storage.APPROVAL_PENDING_REVIEW,
        screenshot_file_id=file_id,
    )

    cfg = onboarding_config.get()
    await update.message.reply_text(
        cfg.pending_review_message,
        parse_mode=ParseMode.MARKDOWN,
    )
    await _notify_admins_for_review(context, user, file_id)


async def _admin_approve(
    update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int
) -> None:
    admin = update.effective_user
    if not admin or not _is_review_admin(admin.id):
        await update.callback_query.answer(
            "Only onboarding reviewers can approve.", show_alert=True
        )
        return

    if storage.get_approval_status(target_user_id) != storage.APPROVAL_PENDING_REVIEW:
        await update.callback_query.answer(
            "This user is not awaiting review.", show_alert=True
        )
        return

    storage.set_approval_status(target_user_id, storage.APPROVAL_APPROVED)
    storage.mark_onboarding_completed(target_user_id)
    jobs.cancel_user_reminders(context.application, target_user_id)
    await airtable_sync.onboarding_completed(target_user_id)
    await unlock_for_user(target_user_id)

    cfg = onboarding_config.get()
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=cfg.approved_message,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.warning(f"Could not DM approved user {target_user_id}: {e}")

    await update.callback_query.answer("Approved ✅ — user unlocked")
    try:
        who = html.escape(admin.username or str(admin.id))
        await update.callback_query.edit_message_caption(
            caption=(
                f"✅ <b>Approved</b> by @{who}\n"
                f"User ID: <code>{target_user_id}</code>"
            ),
            parse_mode=ParseMode.HTML,
        )
    except BadRequest:
        try:
            await update.callback_query.edit_message_text(
                f"✅ Approved by @{admin.username or admin.id} — user {target_user_id}",
            )
        except BadRequest:
            pass


async def _admin_reject(
    update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int
) -> None:
    admin = update.effective_user
    if not admin or not _is_review_admin(admin.id):
        await update.callback_query.answer(
            "Only onboarding reviewers can reject.", show_alert=True
        )
        return

    if storage.get_approval_status(target_user_id) != storage.APPROVAL_PENDING_REVIEW:
        await update.callback_query.answer(
            "This user is not awaiting review.", show_alert=True
        )
        return

    storage.set_approval_status(target_user_id, storage.APPROVAL_AWAITING_SCREENSHOT)
    cfg = onboarding_config.get()
    reason = (
        "The screenshot wasn't clear enough or didn't show a linked trading account."
    )
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=cfg.rejected_message.format(reason=reason),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.warning(f"Could not DM rejected user {target_user_id}: {e}")

    await update.callback_query.answer("Rejected — user asked to resubmit")
    try:
        who = html.escape(admin.username or str(admin.id))
        await update.callback_query.edit_message_caption(
            caption=(
                f"❌ <b>Rejected</b> by @{who}\n"
                f"User ID: <code>{target_user_id}</code>"
            ),
            parse_mode=ParseMode.HTML,
        )
    except BadRequest:
        pass


# ---------- Callback router ----------

@log_call
async def on_onboarding_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if await block_if_group_chat(
        update, context, flow=FLOW_WELCOME, command="onboarding"
    ):
        return

    query = update.callback_query
    await safe_answer_callback(query)
    data = query.data or "" if query else ""
    action = _onb_action(data)
    logger.info(f"onboarding callback: {data!r} -> action={action!r}")

    if action in ("welcome", "start"):
        await show_welcome(update, context)
    elif action == "continue_intro":
        # Legacy button from older messages — go straight to location.
        await show_location(update, context)
    elif action in ("show_location", "location"):
        await show_location(update, context)
    elif action.startswith("loc:"):
        location_id = action.split(":", 1)[1]
        await _send_location_doc(update, context, location_id)
        await show_checklist(update, context)
    elif action == "checklist":
        await show_checklist(update, context)
    elif action == "continue":
        await show_continue(update, context)
    elif action == "confirm_ready":
        await confirm_ready(update, context)
    elif action == "contact_done":
        await contact_done(update, context)
    elif action == "accept_terms":
        await accept_terms(update, context)
    elif action.startswith("approve:"):
        try:
            target_id = int(action.split(":", 1)[1])
        except ValueError:
            await update.callback_query.answer("Invalid user.", show_alert=True)
            return
        await _admin_approve(update, context, target_id)
    elif action.startswith("reject:"):
        try:
            target_id = int(action.split(":", 1)[1])
        except ValueError:
            await update.callback_query.answer("Invalid user.", show_alert=True)
            return
        await _admin_reject(update, context, target_id)
    else:
        logger.warning(f"Unknown onboarding action: {data}")


@log_call
async def cmd_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/onboarding` — restart the welcome flow (for testing)."""
    if not await ensure_welcome_context(update, context):
        return

    user = update.effective_user
    if user and await needs_claim_only_menu(context.bot, user.id):
        await update.message.reply_text(
            join_main_before_onboarding_hint(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    storage.upsert_user(
        user.id,
        onboarding_completed=False,
        onboarding_completed_at=None,
        approval_status=storage.APPROVAL_NONE,
        screenshot_file_id=None,
        terms_accepted_at=None,
        terms_accepted=False,
        checklist={},
    )
    await show_welcome(update, context)


def needs_onboarding(user_id: int) -> bool:
    return storage.needs_onboarding_flow(user_id)


# ---------- Internal helpers ----------

def _progress_bar(done: int, total: int, width: int = 10) -> str:
    if total == 0:
        return ""
    filled = round(width * done / total)
    return "▰" * filled + "▱" * (width - filled)


def _review_admin_ids() -> list[int]:
    from config import settings
    return settings.onboarding_review_admin_ids


def _is_review_admin(user_id: int) -> bool:
    return user_id in _review_admin_ids()


def _telegram_username_line(user) -> str:
    """Plain-text @handle for captions (no Markdown)."""
    if user.username:
        return f"@{user.username}"
    return "Not set"


def _review_caption_html(user, record: dict) -> str:
    """Admin review caption — HTML avoids Markdown breaking on @ symbols."""
    name = html.escape(
        " ".join(p for p in [user.first_name, user.last_name] if p) or "—"
    )
    username = html.escape(_telegram_username_line(user))
    location = html.escape(str(record.get("location", "—")))
    platform = html.escape(str(record.get("platform", "—")))
    terms_at = html.escape(str(record.get("terms_accepted_at", "—")))
    return (
        "<b>📸 Onboarding screenshot — review required</b>\n\n"
        f"• User: {name}\n"
        f"• ID: <code>{user.id}</code>\n"
        f"• Username: {username}\n"
        f"• Location: {location}\n"
        f"• Platform: {platform}\n"
        f"• T&amp;C accepted: {terms_at}"
    )


def _terms_accepted_caption_html(user, accepted_at: str) -> str:
    name = html.escape(
        " ".join(p for p in [user.first_name, user.last_name] if p) or "—"
    )
    username = html.escape(_telegram_username_line(user))
    when = html.escape(accepted_at)
    return (
        "<b>✅ Terms &amp; Disclaimer accepted</b>\n\n"
        f"• User: {name}\n"
        f"• ID: <code>{user.id}</code>\n"
        f"• Username: {username}\n"
        f"• Accepted at: {when}"
    )


async def _notify_admins_terms_accepted(
    context: ContextTypes.DEFAULT_TYPE, user, accepted_at: str
) -> None:
    caption = _terms_accepted_caption_html(user, accepted_at)
    for admin_id in _review_admin_ids():
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=caption,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(f"Could not notify admin {admin_id} of T&C accept: {e}")


async def _notify_admins_for_review(
    context: ContextTypes.DEFAULT_TYPE, user, file_id: str
) -> None:
    """Send screenshot to admins with Approve / Reject buttons."""
    record = storage.get_user(user.id) or {}
    caption = _review_caption_html(user, record)
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Approve", callback_data=f"onb:approve:{user.id}"
                ),
                InlineKeyboardButton(
                    "❌ Reject", callback_data=f"onb:reject:{user.id}"
                ),
            ]
        ]
    )
    review_ids = _review_admin_ids()
    if not review_ids:
        logger.error(
            "No TELEGRAM_REVIEW_ADMIN_IDS (or TELEGRAM_ADMIN_IDS) configured — "
            "screenshot not sent to any reviewer"
        )
        return

    for admin_id in review_ids:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=file_id,
                caption=caption,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(f"Could not send review request to admin {admin_id}: {e}")
