"""Parse gross amount, fees, and net from Whop payment webhook payloads."""

from __future__ import annotations

from typing import Any


def _to_major(value: Any) -> float:
    if value is None:
        return 0.0
    amount = float(value)
    if isinstance(value, int) or (isinstance(value, float) and amount.is_integer()):
        if abs(amount) >= 100:
            return amount / 100.0
    return amount


def parse_whop_payment_amounts(entity: dict) -> tuple[float, float, float, str]:
    """
    Return ``(amount, fees, net_amount, currency)`` in major currency units.

    * *amount* — customer-facing gross total
    * *fees* — Whop / platform transaction fees
    * *net_amount* — amount minus fees (seller payout)
    """
    currency = str(entity.get("currency") or "USD").upper()

    amount = _to_major(
        entity.get("amount")
        or entity.get("subtotal")
        or entity.get("total")
        or entity.get("total_amount")
        or 0
    )

    fees_raw = (
        entity.get("fees")
        or entity.get("application_fee")
        or entity.get("application_fee_amount")
        or entity.get("platform_fee")
        or entity.get("whop_fee")
        or entity.get("transaction_fee")
    )
    fees = _to_major(fees_raw) if fees_raw is not None else 0.0

    net_raw = (
        entity.get("net_amount")
        or entity.get("net")
        or entity.get("seller_amount")
        or entity.get("payout_amount")
        or entity.get("amount_after_fees")
    )
    if net_raw is not None:
        net_amount = _to_major(net_raw)
    elif amount:
        net_amount = amount - fees
    else:
        net_amount = 0.0

    if amount == 0.0 and net_amount:
        amount = net_amount + fees

    return amount, fees, net_amount, currency
