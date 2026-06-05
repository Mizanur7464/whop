"""
User-facing Whop / claim copy.

WHOP_FREE_ACCESS=true  → free registration (tracking only, no payment wording).
WHOP_FREE_ACCESS=false → paid checkout wording (default for future premium).
"""

from __future__ import annotations

from config import settings


def is_free_access() -> bool:
    return bool(settings.whop_free_access)


def claim_email_prompt() -> str:
    if is_free_access():
        return (
            "Thanks for registering for Fusion Strategy through Whop.\n\n"
            "Reply with the *email address* you used there "
            "(one message). We will link your access and send your "
            "Telegram group invite here."
        )
    return (
        "Thanks for registering for Fusion Strategy through Whop.\n\n"
        "Reply with the *email address* you used at checkout "
        "(one message). We will link your membership and send your "
        "Telegram group invite here."
    )


def claim_success_message() -> str:
    return (
        "Your membership is linked.\n\n"
        "Check this chat for the group link and join the group. "
        "After you have done that, come back and enter `/onboarding` "
        "to gain access to the channels in the community."
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
        "Please join the *main community group* first "
        "(use the invite link in this chat).\n\n"
        "After you have joined, send `/onboarding` again."
    )


def claim_only_command_hint() -> str:
    if is_free_access():
        return (
            "Join the *main community* first using the invite link we sent here.\n\n"
            "Until you're in that group, only `/claim` is available "
            "(link your Whop registration)."
        )
    return (
        "Join the *main community* first using the invite link we sent here.\n\n"
        "Until you're in that group, only `/claim` is available."
    )


def claim_already_linked() -> str:
    if is_free_access():
        return (
            "Your Whop access is *already linked* to this Telegram account.\n\n"
            "• Group invite was sent here earlier — check this chat.\n"
            "• Still setting up? Send `/onboarding`.\n"
            "• Need help? Tap `/support`."
        )
    return (
        "Your Whop membership is *already linked* to this Telegram account.\n\n"
        "• Group invite was sent here earlier — check this chat.\n"
        "• Still setting up? Send `/onboarding`.\n"
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
    if is_free_access():
        return "Preparing your Telegram group invite…"
    return "Preparing your Telegram group invite…"


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
