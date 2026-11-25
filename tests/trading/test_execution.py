from decimal import Decimal

import pytest

from crypto_lab.models import (
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketEventEnvelope,
    Ticker,
    TransportType,
)
from crypto_lab.trading import (
    ExecutionSimulator,
    InsufficientBalanceError,
    OrderService,
    OrderSide,
    OrderStatus,
    OrderType,
    create_paper_account,
)


def buy_order() -> tuple[OrderService, ExecutionSimulator, str]:
    orders = OrderService(create_paper_account(ExchangeId.BINANCE))
    order = orders.place(
        instrument_id="binance:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.1"),
        limit_price=Decimal("50000"),
        estimated_buy_fee_rate=Decimal("0.001"),
    )
    return orders, ExecutionSimulator(orders), order.order_id


def ticker_event(ask: str = "49000", bid: str = "48999") -> MarketEventEnvelope[Ticker]:
    return MarketEventEnvelope[Ticker](
        event_id="ticker",
        event_type="TICKER",
        exchange_id=ExchangeId.BINANCE,
        instrument_id="binance:SPOT:BTC/USDT",
        source_type=DataSourceType.MOCK,
        transport=TransportType.FILE,
        received_ts_ms=1,
        quality_status=DataQualityStatus.VALID,
        payload=Ticker(bid=bid, ask=ask, last="1"),
    )


def test_full_buy_settles_assets_fee_and_price_improvement() -> None:
    orders, simulator, order_id = buy_order()
    execution = simulator.execute(
        order_id,
        price=Decimal("49000"),
        quantity=Decimal("0.1"),
        fee_rate=Decimal("0.001"),
    )

    order = orders.get(order_id)
    assert order.status is OrderStatus.FILLED
    assert order.average_fill_price == Decimal("49000")
    assert orders.ledger.balance("BTC").available == Decimal("0.1")
    assert orders.ledger.balance("USDT").available == Decimal("5095.1000")
    assert orders.ledger.balance("USDT").locked == 0
    assert execution.fee_amount == Decimal("4.9000")


def test_partial_buy_then_cancel_releases_remaining_reservation() -> None:
    orders, simulator, order_id = buy_order()
    simulator.execute(
        order_id,
        price=Decimal("49000"),
        quantity=Decimal("0.04"),
        fee_rate=Decimal("0.001"),
    )

    partial = orders.get(order_id)
    assert partial.status is OrderStatus.PARTIALLY_FILLED
    assert orders.ledger.balance("USDT").locked == Decimal("3043.04000")

    canceled = orders.cancel(order_id)
    assert canceled.status is OrderStatus.CANCELED
    assert orders.ledger.balance("USDT").locked == 0
    assert orders.ledger.balance("USDT").available == Decimal("8038.04000")


def test_full_sell_credits_quote_proceeds_less_fee() -> None:
    ledger = create_paper_account(
        ExchangeId.BINANCE,
        initial_asset="BTC",
        initial_amount=Decimal("1"),
    )
    orders = OrderService(ledger)
    order = orders.place(
        instrument_id="binance:SPOT:BTC/USDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.25"),
        limit_price=Decimal("60000"),
    )
    simulator = ExecutionSimulator(orders)
    simulator.execute(
        order.order_id,
        price=Decimal("61000"),
        quantity=Decimal("0.25"),
        fee_rate=Decimal("0.001"),
    )

    assert orders.ledger.balance("BTC").available == Decimal("0.75")
    assert orders.ledger.balance("BTC").locked == 0
    assert orders.ledger.balance("USDT").available == Decimal("15234.75000")


def test_limit_price_protection_rejects_bad_fill_without_changes() -> None:
    orders, simulator, order_id = buy_order()
    entry_count = len(orders.ledger.entries)

    with pytest.raises(ValueError, match="above its limit"):
        simulator.execute(
            order_id,
            price=Decimal("50001"),
            quantity=Decimal("0.1"),
            fee_rate=Decimal("0.001"),
        )

    assert orders.get(order_id).status is OrderStatus.OPEN
    assert len(orders.ledger.entries) == entry_count
    assert simulator.executions() == ()


def test_execution_cannot_exceed_remaining_quantity() -> None:
    _, simulator, order_id = buy_order()

    with pytest.raises(ValueError, match="exceeds remaining"):
        simulator.execute(
            order_id,
            price=Decimal("49000"),
            quantity=Decimal("0.11"),
            fee_rate=Decimal("0.001"),
        )


def test_settlement_batch_is_atomic_when_fee_reservation_is_insufficient() -> None:
    orders = OrderService(create_paper_account(ExchangeId.BINANCE))
    order = orders.place(
        instrument_id="binance:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
        market_reference_price=Decimal("50000"),
    )
    simulator = ExecutionSimulator(orders)
    entries_before = orders.ledger.entries

    with pytest.raises(InsufficientBalanceError):
        simulator.execute(
            order.order_id,
            price=Decimal("50000"),
            quantity=Decimal("0.1"),
            fee_rate=Decimal("0.001"),
        )

    assert orders.ledger.entries == entries_before
    assert orders.get(order.order_id).status is OrderStatus.OPEN
    assert simulator.executions() == ()


def test_market_buy_executes_at_ask_not_last() -> None:
    orders = OrderService(create_paper_account(ExchangeId.BINANCE))
    order = orders.place(
        instrument_id="binance:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
        market_reference_price=Decimal("49000"),
        estimated_buy_fee_rate=Decimal("0.001"),
    )
    simulator = ExecutionSimulator(orders)

    execution = simulator.execute_from_ticker(
        order.order_id,
        ticker_event(ask="49000", bid="48999"),
        quantity=Decimal("0.1"),
        fee_rate=Decimal("0.001"),
    )

    assert execution.price == Decimal("49000")
    assert execution.price != Decimal("1")


def test_invalid_ticker_returns_structured_failure_without_mutation() -> None:
    orders, simulator, order_id = buy_order()
    ticker = ticker_event().model_copy(update={"quality_status": DataQualityStatus.STALE})
    entries_before = orders.ledger.entries

    result = simulator.try_execute_from_ticker(
        order_id,
        ticker,
        quantity=Decimal("0.1"),
        fee_rate=Decimal("0.001"),
    )

    assert not result.success
    assert result.error_type == "ValueError"
    assert result.execution is None
    assert orders.ledger.entries == entries_before
