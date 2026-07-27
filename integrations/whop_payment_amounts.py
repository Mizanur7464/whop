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
    payment = entity.get("payment") if isinstance(entity.get("payment"), dict) else {}
    plan = entity.get("plan") if isinstance(entity.get("plan"), dict) else {}
    product = entity.get("product") if isinstance(entity.get("product"), dict) else {}
    renewal = (
        entity.get("renewal")
        if isinstance(entity.get("renewal"), dict)
        else {}
    )

    currency = str(
        entity.get("currency")
        or payment.get("currency")
        or plan.get("currency")
        or product.get("currency")
        or "USD"
    ).upper()

    amount = _to_major(
        entity.get("amount")
        or entity.get("subtotal")
        or entity.get("total")
        or entity.get("total_amount")
        or payment.get("amount")
        or payment.get("subtotal")
        or payment.get("total")
        or payment.get("total_amount")
        or renewal.get("amount")
        or plan.get("renewal_price")
        or plan.get("price")
        or product.get("renewal_price")
        or product.get("price")
        or 0
    )

    fees_raw = (
        entity.get("fees")
        or entity.get("application_fee")
        or entity.get("application_fee_amount")
        or entity.get("platform_fee")
        or entity.get("whop_fee")
        or entity.get("transaction_fee")
        or payment.get("fees")
        or payment.get("application_fee")
        or payment.get("application_fee_amount")
        or payment.get("platform_fee")
        or payment.get("whop_fee")
        or payment.get("transaction_fee")
    )
    fees = _to_major(fees_raw) if fees_raw is not None else 0.0

    net_raw = (
        entity.get("net_amount")
        or entity.get("net")
        or entity.get("seller_amount")
        or entity.get("payout_amount")
        or entity.get("amount_after_fees")
        or payment.get("net_amount")
        or payment.get("net")
        or payment.get("seller_amount")
        or payment.get("payout_amount")
        or payment.get("amount_after_fees")
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


def parse_whop_payment_category(entity: dict) -> str:
    """Return ``subscription`` or ``one time payment`` for Airtable Category."""
    from airtable.schema import PaymentCategory

    membership = (
        entity.get("membership") if isinstance(entity.get("membership"), dict) else {}
    )
    product = entity.get("product") if isinstance(entity.get("product"), dict) else {}

    hints: list[Any] = [
        entity.get("billing_reason"),
        entity.get("payment_type"),
        entity.get("type"),
        entity.get("plan_type"),
        membership.get("plan_type"),
        membership.get("renewal"),
        product.get("plan_type"),
        product.get("billing_period"),
        product.get("renewal_period"),
    ]

    for raw in hints:
        if raw is None:
            continue
        val = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
        if any(
            token in val
            for token in ("subscription", "recurring", "renewal", "cycle")
        ):
            return PaymentCategory.SUBSCRIPTION.value
        if any(token in val for token in ("one_time", "onetime", "single", "lifetime")):
            return PaymentCategory.ONE_TIME.value
        if val in {"monthly", "yearly", "weekly", "annual", "quarterly"}:
            return PaymentCategory.SUBSCRIPTION.value

    if entity.get("is_renewal") or membership.get("renewal"):
        return PaymentCategory.SUBSCRIPTION.value

    period = product.get("billing_period") or product.get("renewal_period")
    if period and str(period).strip().lower() not in {
        "one_time",
        "onetime",
        "lifetime",
        "none",
        "",
    }:
        return PaymentCategory.SUBSCRIPTION.value

    if membership.get("id") or entity.get("membership_id"):
        return PaymentCategory.SUBSCRIPTION.value

    return PaymentCategory.ONE_TIME.value
