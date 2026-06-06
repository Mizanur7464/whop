"""
User-facing Whop / claim copy.

WHOP_FREE_ACCESS=true  → free registration (tracking only, no payment wording).
WHOP_FREE_ACCESS=false → paid checkout wording (default for future premium).
"""

from __future__ import annotations

from config import settings


def is_free_access() -> bool:
    return bool(settings.whop_free_access)


def claim_processing_message() -> str:
    return "Processing............"


def claim_email_prompt() -> str:
    if is_free_access():
        return (
            "Thanks for registering for Fusion Strategy through Whop.\n\n"
            "Reply with the *email address* you used there "
            "(one message). We will link your access, then you can "
            "complete `/onboarding` in this chat."
        )
    return (
        "Thanks for registering for Fusion Strategy through Whop.\n\n"
        "Reply with the *email address* you used at checkout "
        "(one message). We will link your membership, then you can "
        "complete `/onboarding` in this chat."
    )


def claim_success_message() -> str:
    return (
        "Your membership is linked.\n\n"
        "Send `/onboarding` now to complete the welcome steps and "
        "submit your screenshot.\n\n"
        "After our team approves, we will send your *main group invite* "
        "here in this chat."
    )


def claim_invite_message(invite_url: str) -> str:
    return f"🎉 Your main group invite:\n{invite_url}"


def claim_invite_failed_message() -> str:
    return (
        "We could not generate your group invite link right now.\n\n"
        "Please wait 30 seconds and send `/claim` again, or contact support."
    )


def grant_access_invite_footer() -> str:
    return (
        "After joining, come back here and send `/onboarding` "
        "to gain access to the channels in the community."
    )


def claim_email_not_found() -> str:
    if is_free_access():
        return (
            "We could not find a registration for that email yet.\n\n"
            "• Finish the *free Whop* signup first (same link from the group).\n"
            "• Wait 30–60 seconds, then try again.\n"
            "• Use the *exact* email from Whop (check spelling).\n"
            "• Or open the page after Whop — your *activation code* is there.\n"
            "• Still stuck? Tap /support."
        )
    return (
        "We could not find a payment for that email yet.\n\n"
        "• Wait 30–60 seconds after paying, then try again.\n"
        "• Use the same email as on your Whop receipt.\n"
        "• Still stuck? Tap /support."
    )


def join_main_before_onboarding_hint() -> str:
    return (
        "Please send `/onboarding` first to complete welcome setup.\n\n"
        "After admin approval we will send your main group invite here."
    )


def claim_only_command_hint() -> str:
    return (
        "Complete `/onboarding` first.\n\n"
        "Until you are approved, only `/start`, `/claim`, and `/onboarding` "
        "are available. Your main group invite comes after approval."
    )


def claim_already_linked() -> str:
    if is_free_access():
        return (
            "Your Whop access is *already linked* to this Telegram account.\n\n"
            "• Send `/onboarding` to continue setup.\n"
            "• Main group invite is sent *after* admin approval.\n"
            "• Need help? Tap `/support`."
        )
    return (
        "Your Whop membership is *already linked* to this Telegram account.\n\n"
        "• Send `/onboarding` to continue setup.\n"
        "• Main group invite is sent *after* admin approval.\n"
        "• Need help? Tap `/support`."
    )


def claim_code_not_found() -> str:
    if is_free_access():
        return (
            "We couldn't find that activation code. It may have already been used.\n\n"
            "Just registered on Whop? Send `/claim` and reply with your Whop email."
        )
    return (
        "We couldn't find that claim code. It may have already been used.\n\n"
        "Just paid? Send `/claim` and reply with your Whop checkout email."
    )


def membership_received_dm(*, success_hint: str, bot_link: str) -> list[str]:
    if is_free_access():
        return [
            "Your Whop registration was received.",
            "",
            "To get your Telegram group invite:",
            f"1. Open {success_hint} (your activation code is there), or",
            f"2. Open {bot_link} → send `/claim` → reply with your Whop email.",
            "",
            "Your invite link will appear in Telegram.",
        ]
    return [
        "Your Whop payment was received.",
        "",
        "To get your Telegram group invite:",
        f"1. Open {success_hint} (your activation code is there), or",
        f"2. Open {bot_link} → send `/claim` → reply with your Whop email.",
        "",
        "Your invite link will appear in Telegram.",
    ]


def success_page_title() -> str:
    if is_free_access():
        return "Access activated — Fusion Strategy"
    return "Payment successful — Fusion Strategy"


def success_page_heading() -> str:
    if is_free_access():
        return "Access activated"
    return "Payment successful"


def success_page_subtitle() -> str:
    return (
        "Thank you for joining Fusion Strategy through Whop. "
        "Use the steps below to open Telegram access."
    )


def success_page_preparing() -> str:
    return (
        "Linking your Whop registration. "
        "This can take 1-2 minutes, don't close this screen"
    )


def success_page_ready_message() -> str:
    return (
        "You're registered. Open our Telegram bot and send /onboarding "
        "to complete setup. Your main group invite will be sent after we approve."
    )


def success_page_invite_heading() -> str:
    return "Join the main community group"


def success_page_invite_hint() -> str:
    return (
        "This link is personal and one-time use. After joining, open our bot "
        "and send /onboarding to finish setup."
    )


def success_page_still_processing() -> str:
    if is_free_access():
        return "Still linking your Whop registration."
    return "Still processing your payment."


def success_page_wait_hint() -> str:
    if is_free_access():
        return (
            "Send <span class=\"cmd\">/claim</span> in the bot, then reply with the "
            "<strong>email</strong> you used on Whop."
        )
    return (
        "Send <span class=\"cmd\">/claim</span> in the bot, then reply with the "
        "<strong>email</strong> you used on Whop."
    )
