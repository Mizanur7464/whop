"""
Finance commands (admin only).

    /expense <amount> <currency> <category> <description...>
        e.g. /expense 75 USD Ads Facebook spend for May

    /revenue [days]
        Show revenue totals for the last N days (default 30)

    /expenses [days]
        Show expense totals for the last N days (default 30)

    /pnl [days]
        Profit & Loss summary
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from airtable import sync as airtable_sync
from airtable.client import AirtableClient, normalize_currency
from airtable.schema import ExpenseCategory, FinanceField, SUPPORTED_CURRENCIES
from bot.decorators import admin_only, log_call


_VALID_CATEGORIES = [c.value for c in ExpenseCategory]


def _parse_int(arg: str, default: int) -> int:
    try:
        return max(1, int(arg))
    except (TypeError, ValueError):
        return default


def _fmt_money(amount: float, currency: str) -> str:
    return f"{amount:,.2f} {currency.upper()}"


def _format_by_currency(totals: dict[str, float]) -> str:
    if not totals:
        return "—"
    parts = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return ", ".join(_fmt_money(v, c) for c, v in parts)


# ---------- /expense ----------

@admin_only
@log_call
async def cmd_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage:\n"
            "`/expense <amount> <currency> <category> <description>`\n\n"
            f"Categories: {', '.join(_VALID_CATEGORIES)}\n"
            f"Currencies: {', '.join(sorted(SUPPORTED_CURRENCIES))}\n\n"
            "Example: `/expense 75 USD Ads Facebook campaign May`\n"
            "Use negative amounts for refunds/credits.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    raw_amount, currency, category, *desc_parts = context.args
    description = " ".join(desc_parts)
    currency_code = normalize_currency(currency)

    try:
        amount = float(raw_amount.replace(",", ""))
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return

    if currency.strip().upper() not in SUPPORTED_CURRENCIES:
        await update.message.reply_text(
            f"Currency must be one of: {', '.join(sorted(SUPPORTED_CURRENCIES))}"
        )
        return

    if category.title() not in _VALID_CATEGORIES:
        await update.message.reply_text(
            f"Unknown category `{category}`.\nValid: {', '.join(_VALID_CATEGORIES)}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    user = update.effective_user
    added_by = f"@{user.username}" if user.username else str(user.id)

    client = airtable_sync.client()
    if not client.enabled:
        await update.message.reply_text(
            "❌ Airtable is not configured. Set `AIRTABLE_API_KEY` and "
            "`AIRTABLE_BASE_ID` in `.env`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    rec = await client.add_expense(
        amount=amount,
        currency=currency_code,
        category=category.title(),
        description=description,
        added_by=added_by,
    )

    if rec:
        stored = rec.get("fields") or {}
        amt = float(
            stored.get(FinanceField.AMOUNT)
            or stored.get(FinanceField.NET_AMOUNT)
            or amount
        )
        fee = float(stored.get(FinanceField.FEES) or 0)
        net = float(stored.get(FinanceField.NET_AMOUNT) or amt)
        await update.message.reply_text(
            "✅ Expense logged\n\n"
            f"• Amount: {_fmt_money(amt, currency_code)}\n"
            f"• Fees: {_fmt_money(fee, currency_code)}\n"
            f"• Net: {_fmt_money(net, currency_code)}\n"
            f"• {category.title()} — {description}",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "❌ Could not write to Airtable. Check logs."
        )


# ---------- /revenue ----------

@admin_only
@log_call
async def cmd_revenue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    days = _parse_int(context.args[0] if context.args else "30", 30)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    client = AirtableClient()
    if not client.enabled:
        await update.message.reply_text("❌ Airtable not configured.")
        return

    summary = await client.revenue_summary(since=since)
    by_curr = summary.get("by_currency", {})
    count = summary.get("count", 0)

    body = (
        f"💰 *Revenue — last {days} days*\n\n"
        f"• Payments: *{count}*\n"
        f"• Totals: *{_format_by_currency(by_curr)}*"
    )
    await update.message.reply_text(body, parse_mode=ParseMode.MARKDOWN)


# ---------- /expenses ----------

@admin_only
@log_call
async def cmd_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    days = _parse_int(context.args[0] if context.args else "30", 30)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    client = AirtableClient()
    if not client.enabled:
        await update.message.reply_text("❌ Airtable not configured.")
        return

    summary = await client.expense_summary(since=since)
    by_curr = summary.get("by_currency", {})
    by_cat = summary.get("by_category", {})
    count = summary.get("count", 0)

    cat_lines = [
        f"  • {cat}: {amount:,.2f}"
        for cat, amount in sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True)
    ]
    cat_block = "\n".join(cat_lines) if cat_lines else "  —"

    body = (
        f"💸 *Expenses — last {days} days*\n\n"
        f"• Entries: *{count}*\n"
        f"• Totals: *{_format_by_currency(by_curr)}*\n\n"
        f"*By category:*\n{cat_block}"
    )
    await update.message.reply_text(body, parse_mode=ParseMode.MARKDOWN)


# ---------- /pnl ----------

@admin_only
@log_call
async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    days = _parse_int(context.args[0] if context.args else "30", 30)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    client = AirtableClient()
    if not client.enabled:
        await update.message.reply_text("❌ Airtable not configured.")
        return

    revenue = await client.revenue_summary(since=since)
    expenses = await client.expense_summary(since=since)

    rev_by = revenue.get("by_currency", {})
    exp_by = expenses.get("by_currency", {})
    all_curr = sorted(set(rev_by) | set(exp_by))

    lines = []
    for c in all_curr:
        r = rev_by.get(c, 0.0)
        e = exp_by.get(c, 0.0)
        net = r - e
        sign = "🟢" if net >= 0 else "🔴"
        lines.append(
            f"{sign} *{c}*  →  rev {r:,.2f}, exp {e:,.2f}, *net {net:,.2f}*"
        )

    if not lines:
        lines.append("No revenue or expense data in this window.")

    body = (
        f"📊 *P&L — last {days} days*\n\n" + "\n".join(lines)
    )
    await update.message.reply_text(body, parse_mode=ParseMode.MARKDOWN)
