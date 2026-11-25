from decimal import Decimal

import pytest

from crypto_lab.market_data import OrderBookView
from crypto_lab.models import DataQualityStatus, ExchangeId, PriceLevel
from crypto_lab.trading import (
    ExecutionSimulator,
    InsufficientBalanceError,
    MarketRules,
    MarketRuleViolation,
    OrderService,
    OrderSide,
    OrderStatus,
    OrderType,
    SimulatedLiquidityView,
    create_paper_account,
    match_market_order,
)

RULES = MarketRules(
    rules_id="MOCK:BTC-USDT:v1",
    price_increment=Decimal("1"),
    quantity_increment=Decimal("1"),
    min_quantity=Decimal("1"),
    min_notional=Decimal("10"),
)


def market_book(
    *,
    bids: tuple[tuple[str, str], ...] = (("99", "5"),),
    asks: tuple[tuple[str, str], ...] = (("100", "1"), ("101", "2")),
) -> OrderBookView:
    return OrderBookView(
        exchange_id=ExchangeId.OKX,
        instrument_id="okx:SPOT:BTC/USDT",
        bids=tuple(PriceLevel(price=price, quantity=quantity) for price, quantity in bids),
        asks=tuple(PriceLevel(price=price, quantity=quantity) for price, quantity in asks),
        depth=20,
        sequence_id="10",
        source_event_id="book-10",
        exchange_ts_ms=900,
        received_ts_ms=1_000,
        quality_status=DataQualityStatus.VALID,
        synchronized=True,
        source_connected=True,
    )


def buy_context(
    *, quantity: str, reference_price: str, fee_buffer: str
) -> tuple[OrderService, ExecutionSimulator, SimulatedLiquidityView, str]:
    orders = OrderService(create_paper_account(ExchangeId.OKX))
    order = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(quantity),
        market_reference_price=Decimal(reference_price),
        estimated_buy_fee_rate=Decimal(fee_buffer),
    )
    return orders, ExecutionSimulator(orders), SimulatedLiquidityView("run-1"), order.order_id


def test_multi_level_plan_settles_all_fills_without_extra_slippage_charge() -> None:
    orders, simulator, liquidity, order_id = buy_context(
        quantity="3", reference_price="101", fee_buffer="0.001"
    )
    liquidity.synchronize(market_book())
    plan = match_market_order(
        liquidity.available_book(),
        side=OrderSide.BUY,
        quantity=Decimal("3"),
        submission_reference_price=Decimal("100"),
    )

    records = simulator.execute_match_plan(
        order_id,
        plan,
        fee_rate=Decimal("0.001"),
        market_rules=RULES,
        liquidity=liquidity,
        consumption_id="match-1",
    )

    assert [record.price for record in records] == [Decimal("100"), Decimal("101")]
    assert orders.get(order_id).status is OrderStatus.FILLED
    assert orders.get(order_id).average_fill_price == Decimal("302") / Decimal("3")
    assert orders.ledger.balance("BTC").available == Decimal("3")
    assert orders.ledger.balance("USDT").available == Decimal("9697.698")
    assert orders.ledger.balance("USDT").locked == 0
    assert liquidity.available_book().asks == ()


def test_insufficient_depth_cancels_remainder_and_releases_reservation() -> None:
    orders, simulator, liquidity, order_id = buy_context(
        quantity="4", reference_price="101", fee_buffer="0.001"
    )
    liquidity.synchronize(market_book())
    plan = match_market_order(
        liquidity.available_book(),
        side=OrderSide.BUY,
        quantity=Decimal("4"),
        submission_reference_price=Decimal("100"),
    )

    records = simulator.execute_match_plan(
        order_id,
        plan,
        fee_rate=Decimal("0.001"),
        market_rules=RULES,
        liquidity=liquidity,
        consumption_id="match-1",
    )

    order = orders.get(order_id)
    assert len(records) == 2
    assert order.status is OrderStatus.CANCELED
    assert order.filled_quantity == Decimal("3")
    assert orders.ledger.balance("USDT").locked == 0


def test_no_liquidity_cancels_order_without_execution() -> None:
    orders, simulator, liquidity, order_id = buy_context(
        quantity="1", reference_price="100", fee_buffer="0.001"
    )
    liquidity.synchronize(market_book(asks=()))
    plan = match_market_order(
        liquidity.available_book(),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        submission_reference_price=Decimal("100"),
    )

    records = simulator.execute_match_plan(
        order_id,
        plan,
        fee_rate=Decimal("0.001"),
        market_rules=RULES,
        liquidity=liquidity,
        consumption_id="match-1",
    )

    assert records == ()
    assert orders.get(order_id).status is OrderStatus.CANCELED
    assert orders.ledger.balance("USDT").locked == 0
    assert simulator.executions() == ()


def test_settlement_failure_does_not_consume_liquidity_or_update_order() -> None:
    orders, simulator, liquidity, order_id = buy_context(
        quantity="1", reference_price="100", fee_buffer="0"
    )
    liquidity.synchronize(market_book(asks=(("100", "1"),)))
    plan = match_market_order(
        liquidity.available_book(),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        submission_reference_price=Decimal("100"),
    )
    before_book = liquidity.available_book()
    before_entries = orders.ledger.entries

    with pytest.raises(InsufficientBalanceError):
        simulator.execute_match_plan(
            order_id,
            plan,
            fee_rate=Decimal("0.001"),
            market_rules=RULES,
            liquidity=liquidity,
            consumption_id="match-1",
        )

    assert orders.get(order_id).status is OrderStatus.OPEN
    assert orders.ledger.entries == before_entries
    assert liquidity.available_book() == before_book
    assert simulator.executions() == ()


def test_market_sell_settles_multiple_bid_levels() -> None:
    ledger = create_paper_account(
        ExchangeId.OKX,
        initial_asset="BTC",
        initial_amount=Decimal("3"),
    )
    orders = OrderService(ledger)
    order = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("3"),
        market_reference_price=Decimal("99"),
    )
    simulator = ExecutionSimulator(orders)
    liquidity = SimulatedLiquidityView("run-1")
    liquidity.synchronize(market_book(bids=(("99", "1"), ("98", "2"))))
    plan = match_market_order(
        liquidity.available_book(),
        side=OrderSide.SELL,
        quantity=Decimal("3"),
        submission_reference_price=Decimal("99"),
    )

    simulator.execute_match_plan(
        order.order_id,
        plan,
        fee_rate=Decimal("0.001"),
        market_rules=RULES,
        liquidity=liquidity,
        consumption_id="match-1",
    )

    assert orders.get(order.order_id).status is OrderStatus.FILLED
    assert orders.ledger.balance("BTC").locked == 0
    assert orders.ledger.balance("USDT").available == Decimal("294.705")


def test_match_plan_must_match_order_side_and_remaining_quantity() -> None:
    orders, simulator, liquidity, order_id = buy_context(
        quantity="1", reference_price="100", fee_buffer="0.001"
    )
    liquidity.synchronize(market_book())
    sell_plan = match_market_order(
        liquidity.available_book(),
        side=OrderSide.SELL,
        quantity=Decimal("1"),
        submission_reference_price=Decimal("99"),
    )

    with pytest.raises(ValueError, match="side"):
        simulator.execute_match_plan(
            order_id,
            sell_plan,
            fee_rate=Decimal("0.001"),
            market_rules=RULES,
            liquidity=liquidity,
            consumption_id="match-1",
        )


def test_market_rules_reject_invalid_quantity_without_mutation() -> None:
    orders, simulator, liquidity, order_id = buy_context(
        quantity="1", reference_price="100", fee_buffer="0.001"
    )
    liquidity.synchronize(market_book())
    plan = match_market_order(
        liquidity.available_book(),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        submission_reference_price=Decimal("100"),
    )
    restrictive = RULES.model_copy(update={"min_quantity": Decimal("2")})
    before_entries = orders.ledger.entries
    before_book = liquidity.available_book()

    with pytest.raises(MarketRuleViolation, match="below"):
        simulator.execute_match_plan(
            order_id,
            plan,
            fee_rate=Decimal("0.001"),
            market_rules=restrictive,
            liquidity=liquidity,
            consumption_id="match-1",
        )

    assert orders.get(order_id).status is OrderStatus.OPEN
    assert orders.ledger.entries == before_entries
    assert liquidity.available_book() == before_book
