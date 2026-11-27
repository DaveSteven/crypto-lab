"""Authoritative Decimal calculations for the P0 Spot Long Trade Planner."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Any

CALCULATOR_VERSION = "spot-long-v1"


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def calculate_plan(
    *,
    entry_price: Decimal,
    planned_position_notional: Decimal,
    stop_loss_price: Decimal,
    take_profit_price: Decimal,
    effective_equity: Decimal | None,
    available_quote_balance: Decimal,
    fee_rate: Decimal | None,
    price_increment: Decimal,
    quantity_increment: Decimal,
    min_quantity: Decimal,
    min_notional: Decimal | None,
    max_position_notional: Decimal,
    max_account_risk_rate: Decimal,
    min_reward_risk_ratio: Decimal,
    market_status: str,
    valuation_status: str,
) -> dict[str, Any]:
    """Calculate a plan without side effects; all inputs are trusted Decimal values."""
    checks: dict[str, dict[str, str]] = {}

    def check(name: str, passed: bool, reason: str) -> None:
        checks[name] = {"status": "PASS" if passed else "FAIL", "reason": reason}

    def unavailable(name: str, reason: str) -> None:
        checks[name] = {"status": "UNAVAILABLE", "reason": reason}

    price_relation = stop_loss_price < entry_price < take_profit_price
    check("price_relationship", price_relation, "requires SL < Entry < TP")
    check(
        "price_precision",
        all(
            value % price_increment == 0
            for value in (entry_price, stop_loss_price, take_profit_price)
        ),
        "all plan prices must align with the market tick size",
    )

    quantity = floor_to_step(planned_position_notional / entry_price, quantity_increment)
    entry_notional = entry_price * quantity
    check("minimum_quantity", quantity >= min_quantity, "quantity must meet market minimum")
    check(
        "minimum_notional",
        min_notional is None or entry_notional >= min_notional,
        "entry notional must meet market minimum",
    )
    check(
        "position_limit",
        planned_position_notional <= max_position_notional,
        "planned notional must not exceed the policy limit",
    )

    if fee_rate is None:
        unavailable("fee_schedule", "actual fee schedule is unavailable")
        entry_fee = exit_fee_at_tp = exit_fee_at_sl = None
        net_profit = net_loss = reward_risk = None
        unavailable("available_balance", "fee-inclusive funding cannot be validated")
        unavailable("account_risk", "fee-inclusive risk cannot be validated")
        unavailable("reward_risk", "fee-inclusive reward/risk cannot be validated")
        maximum_allowed = None
    else:
        check("fee_schedule", True, "uses max(maker,taker) from the actual fee schedule")
        entry_fee = entry_notional * fee_rate
        exit_fee_at_tp = take_profit_price * quantity * fee_rate
        exit_fee_at_sl = stop_loss_price * quantity * fee_rate
        net_profit = (take_profit_price - entry_price) * quantity - entry_fee - exit_fee_at_tp
        net_loss = (entry_price - stop_loss_price) * quantity + entry_fee + exit_fee_at_sl
        reward_risk = net_profit / net_loss if net_loss > 0 else None
        check(
            "available_balance",
            entry_notional + entry_fee <= available_quote_balance,
            "available quote balance must cover entry notional and fee",
        )
        if effective_equity is None or valuation_status != "COMPLETE":
            unavailable("account_risk", "effective account equity valuation is incomplete")
        else:
            account_risk = net_loss / effective_equity if effective_equity > 0 else None
            check(
                "account_risk",
                account_risk is not None and account_risk <= max_account_risk_rate,
                "planned net loss must remain within account risk policy",
            )
        check(
            "reward_risk",
            reward_risk is not None and reward_risk >= min_reward_risk_ratio,
            "net reward/risk ratio must meet policy minimum",
        )
        balance_cap = available_quote_balance / (Decimal(1) + fee_rate)
        loss_per_quantity = (
            entry_price - stop_loss_price + entry_price * fee_rate + stop_loss_price * fee_rate
        )
        risk_cap = None
        if (
            effective_equity is not None
            and valuation_status == "COMPLETE"
            and loss_per_quantity > 0
        ):
            risk_quantity = effective_equity * max_account_risk_rate / loss_per_quantity
            risk_cap = floor_to_step(risk_quantity, quantity_increment) * entry_price
        candidates = [max_position_notional, balance_cap]
        if risk_cap is not None:
            candidates.append(risk_cap)
        maximum_allowed = (
            floor_to_step(min(candidates) / entry_price, quantity_increment) * entry_price
        )

    if market_status == "VALID":
        check("market_data", True, "current valid executable market data is available")
    else:
        unavailable("market_data", "current valid executable market data is unavailable")

    overall = "PASS"
    if any(item["status"] == "FAIL" for item in checks.values()):
        overall = "FAIL"
    elif any(item["status"] == "UNAVAILABLE" for item in checks.values()):
        overall = "UNAVAILABLE"

    position_ratio = None
    account_risk_ratio = None
    if effective_equity is not None and effective_equity > 0 and valuation_status == "COMPLETE":
        position_ratio = entry_notional / effective_equity
        if net_loss is not None:
            account_risk_ratio = net_loss / effective_equity

    def value(item: Decimal | None) -> str | None:
        return None if item is None else str(item)

    return {
        "calculator_version": CALCULATOR_VERSION,
        "validation_status": overall,
        "validations": checks,
        "calculation": {
            "quantity": value(quantity),
            "entry_notional": value(entry_notional),
            "entry_fee": value(entry_fee),
            "exit_fee_at_take_profit": value(exit_fee_at_tp),
            "exit_fee_at_stop_loss": value(exit_fee_at_sl),
            "estimated_net_profit": value(net_profit),
            "estimated_net_loss": value(net_loss),
            "net_reward_risk_ratio": value(reward_risk),
            "account_risk_ratio": value(account_risk_ratio),
            "position_ratio": value(position_ratio),
            "maximum_allowed_position_notional": value(maximum_allowed),
        },
    }
