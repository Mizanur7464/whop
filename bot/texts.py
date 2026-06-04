"""
All user-facing strings live here.

Why a separate module?
    * Buyer can edit copy without touching code
    * Easy to add i18n later (just wrap each string)
    * No magic strings scattered across handlers
"""

from __future__ import annotations

# ---------- Generic ----------
UNAUTHORIZED = "Sorry, you don't have permission to do that."
ERROR_GENERIC = "Something went wrong. The team has been notified."
COMING_SOON = "Coming soon — this feature is being built in the next phase."

# ---------- /start ----------
WELCOME = (
    "Welcome, {first_name}! 👋\n\n"
    "You're now connected to our membership bot. "
    "Use the menu below to get started."
)

WELCOME_RETURNING = (
    "Welcome back, {first_name}! 👋\n\n"
    "Pick an option below to continue."
)

# ---------- /help ----------
HELP_TEXT = (
    "🤖 *Fusion Wealth Bot*\n\n"
    "All flows run here in *private chat* (only you can see your answers).\n\n"
    "/start — Welcome onboarding\n"
    "/onboarding — Restart onboarding\n"
    "/copytrading — Copy trading setup\n"
    "/support — Support form\n"
    "/claim — Link your Whop purchase\n"
    "/help — This message\n\n"
    "_In the group, open the pinned topic and tap “Open bot” — "
    "do not type answers in the group._"
)

HELP_AFTER_ONBOARDING = (
    "✅ *Welcome onboarding is complete.*\n\n"
    "Use this private chat for personal bot flows:\n"
    "• /copytrading — Copy trading setup\n"
    "• /support — Contact the team\n\n"
    "The group is for community content (signals, updates, discussion) — "
    "not for posting your private setup answers."
)

DM_FLOW_INVITE = (
    "👋 *{flow_label}* is only available in private chat with the bot "
    "(other members cannot see your messages).\n\n"
    "Tap *Continue* below — then you can use `/{command}` if needed."
)

BTN_OPEN_BOT_PRIVATE = "▶️ Continue in private chat"

HELP_ADMIN_EXTRA = (
    "\n👑 *Admin Commands*\n\n"
    "/stats — Live member stats\n"
    "/broadcast `<message>` — Send to all members\n"
    "/ban `<user_id>` — Remove a user\n"
    "/unban `<user_id>` — Reinstate a user\n"
    "/status — Build status"
)

# ---------- /profile ----------
PROFILE_TEMPLATE = (
    "👤 *Your Profile*\n\n"
    "• Name: {name}\n"
    "• Telegram ID: `{user_id}`\n"
    "• Plan: {plan}\n"
    "• Member since: {joined}\n"
    "• Status: {status}\n\n"
    "_Need a change? Tap Support below._"
)

PROFILE_NOT_FOUND = (
    "We couldn't find an active membership for your account.\n\n"
    "If you just signed up, please wait 30 seconds and try again. "
    "Still stuck? Tap /support."
)

# ---------- /checklist ----------
CHECKLIST_INTRO = (
    "📋 *Your Onboarding Checklist*\n\n"
    "Complete each step to unlock the full community experience.\n"
    "Tap any item below to mark it done.\n\n"
    "{items}\n\n"
    "Progress: {done}/{total}  {bar}"
)

CHECKLIST_ITEM_DONE = "✅ {title}"
CHECKLIST_ITEM_PENDING = "⬜ {title}"
CHECKLIST_ALL_DONE = (
    "🎉 *Congratulations!* You've completed all onboarding steps.\n\n"
    "You're now a full community member. Enjoy!"
)
CHECKLIST_PLACEHOLDER = (
    "📋 *Checklist*\n\n"
    "Your onboarding checklist will appear here once buyer-provided "
    "tasks are configured (Phase 4)."
)

# ---------- /support ----------
SUPPORT_TEXT = (
    "💬 *Need Help?*\n\n"
    "Reach our team here:\n"
    "• Email: support@example.com\n"
    "• Telegram: @your_support_handle\n\n"
    "Average response time: under 2 hours."
)

# ---------- Admin: /broadcast ----------
BROADCAST_USAGE = (
    "Usage: `/broadcast <your message>`\n\n"
    "Example: `/broadcast New session starts in 1 hour!`"
)
BROADCAST_CONFIRM = (
    "📢 You're about to broadcast to *{count}* members:\n\n"
    "{preview}\n\n"
    "Reply *YES* within 30 seconds to confirm, or anything else to cancel."
)
BROADCAST_SENT = "✅ Broadcast sent to *{count}* members. Failed: {failed}."
BROADCAST_CANCELLED = "Broadcast cancelled."

# ---------- Admin: /ban /unban ----------
BAN_USAGE = "Usage: `/ban <telegram_user_id>`"
UNBAN_USAGE = "Usage: `/unban <telegram_user_id>`"
BAN_SUCCESS = "🚫 User `{user_id}` has been removed."
UNBAN_SUCCESS = "✅ User `{user_id}` has been reinstated."
BAN_FAIL = "Could not ban user `{user_id}`: {reason}"

# ---------- Admin: /stats ----------
STATS_TEMPLATE = (
    "📊 *Live Stats*\n\n"
    "• Total members: *{total}*\n"
    "• Active: *{active}*\n"
    "• Banned: *{banned}*\n"
    "• New today: *{new_today}*\n"
    "• Phase: *{phase}*"
)

# ---------- Menu buttons ----------
BTN_PROFILE = "👤 My Profile"
BTN_CHECKLIST = "📋 Checklist"
BTN_SUPPORT = "💬 Support"
BTN_HELP = "❓ Help"
BTN_BACK = "⬅️ Back"
BTN_CLOSE = "✖️ Close"

# Admin-only buttons
BTN_ADMIN_PANEL = "🔐 Admin panel"
BTN_ADMIN_STATS = "📊 Stats"
BTN_ADMIN_BROADCAST = "📢 Broadcast"
