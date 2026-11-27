from decimal import Decimal

from crypto_lab.api.trade_planner import calculate_plan, floor_to_step


def test_floor_to_step_never_rounds_position_up() -> None:
    assert floor_to_step(Decimal("0.123456789"), Decimal("0.00000001")) == Decimal(
        "0.12345678"
    )


def test_spot_long_preview_uses_fee_in_both_outcomes_and_nominal_position_ratio() -> None:
    result = calculate_plan(
        entry_price=Decimal("100"),
        planned_position_notional=Decimal("100"),
        stop_loss_price=Decimal("95"),
        take_profit_price=Decimal("112"),
        effective_equity=Decimal("751"),
        available_quote_balance=Decimal("751"),
        fee_rate=Decimal("0.001"),
        price_increment=Decimal("0.1"),
        quantity_increment=Decimal("0.00000001"),
        min_quantity=Decimal("0.00001"),
        min_notional=None,
        max_position_notional=Decimal("100"),
        max_account_risk_rate=Decimal("0.01"),
        min_reward_risk_ratio=Decimal("2"),
        market_status="VALID",
        valuation_status="COMPLETE",
    )

    calculation = result["calculation"]
    assert result["validation_status"] == "PASS"
    assert Decimal(calculation["quantity"]) == Decimal("1")
    assert Decimal(calculation["entry_fee"]) == Decimal("0.1")
    assert Decimal(calculation["exit_fee_at_stop_loss"]) == Decimal("0.095")
    assert Decimal(calculation["estimated_net_loss"]) == Decimal("5.195")
    assert Decimal(calculation["position_ratio"]) == Decimal("100") / Decimal("751")


def test_incomplete_equity_and_missing_fee_are_explicitly_unavailable() -> None:
    result = calculate_plan(
        entry_price=Decimal("100"),
        planned_position_notional=Decimal("100"),
        stop_loss_price=Decimal("95"),
        take_profit_price=Decimal("112"),
        effective_equity=None,
        available_quote_balance=Decimal("100"),
        fee_rate=None,
        price_increment=Decimal("0.1"),
        quantity_increment=Decimal("0.01"),
        min_quantity=Decimal("0.01"),
        min_notional=None,
        max_position_notional=Decimal("100"),
        max_account_risk_rate=Decimal("0.01"),
        min_reward_risk_ratio=Decimal("2"),
        market_status="UNAVAILABLE",
        valuation_status="INCOMPLETE",
    )

    assert result["validation_status"] == "UNAVAILABLE"
    assert result["validations"]["fee_schedule"]["status"] == "UNAVAILABLE"
    assert result["validations"]["account_risk"]["status"] == "UNAVAILABLE"
    assert result["validations"]["market_data"]["status"] == "UNAVAILABLE"
    assert result["calculation"]["estimated_net_profit"] is None


def test_invalid_price_relationship_and_precision_fail_without_float_tolerance() -> None:
    result = calculate_plan(
        entry_price=Decimal("100.05"),
        planned_position_notional=Decimal("100"),
        stop_loss_price=Decimal("101"),
        take_profit_price=Decimal("99"),
        effective_equity=Decimal("1000"),
        available_quote_balance=Decimal("1000"),
        fee_rate=Decimal("0.001"),
        price_increment=Decimal("0.1"),
        quantity_increment=Decimal("0.0001"),
        min_quantity=Decimal("0.0001"),
        min_notional=None,
        max_position_notional=Decimal("100"),
        max_account_risk_rate=Decimal("0.01"),
        min_reward_risk_ratio=Decimal("2"),
        market_status="VALID",
        valuation_status="COMPLETE",
    )

    assert result["validation_status"] == "FAIL"
    assert result["validations"]["price_relationship"]["status"] == "FAIL"
    assert result["validations"]["price_precision"]["status"] == "FAIL"
