from decimal import Decimal

import pytest

from crypto_lab.models import ExchangeId
from crypto_lab.trading import (
    FeeSchedule,
    InsufficientBalanceError,
    InvalidOrderTransitionError,
    OrderService,
    OrderSide,
    OrderStatus,
    OrderType,
    create_paper_account,
)


class ManualTime:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def service(initial_amount: str = "10000") -> OrderService:
    ledger = create_paper_account(
        ExchangeId.BINANCE,
        initial_amount=Decimal(initial_amount),
    )
    return OrderService(ledger)


def test_limit_buy_reserves_quote_notional_and_fee_buffer() -> None:
    orders = service()
    order = orders.place(
        instrument_id="binance:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.1"),
        limit_price=Decimal("50000"),
        estimated_buy_fee_rate=Decimal("0.001"),
    )

    assert order.status is OrderStatus.OPEN
    assert order.reserved_asset == "USDT"
    assert order.reserved_amount == Decimal("5005.0000")
    assert orders.ledger.balance("USDT").locked == Decimal("5005.0000")


def test_sell_reserves_base_asset() -> None:
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

    assert order.reserved_asset == "BTC"
    assert orders.ledger.balance("BTC").available == Decimal("0.75")
    assert orders.ledger.balance("BTC").locked == Decimal("0.25")


def test_market_buy_requires_executable_reference_price() -> None:
    orders = service()

    with pytest.raises(ValueError, match="executable reference"):
        orders.place(
            instrument_id="binance:SPOT:BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )


def test_market_buy_uses_reference_price_for_reservation() -> None:
    orders = service()
    order = orders.place(
        instrument_id="binance:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
        market_reference_price=Decimal("50000"),
    )

    assert order.reference_price == Decimal("50000")
    assert order.limit_price is None
    assert order.reserved_amount == Decimal("5000.0")


def test_insufficient_balance_rejects_order_without_recording_it() -> None:
    orders = service("100")

    with pytest.raises(InsufficientBalanceError):
        orders.place(
            instrument_id="binance:SPOT:BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            limit_price=Decimal("50000"),
        )

    assert orders.orders() == ()
    assert orders.ledger.balance("USDT").available == Decimal("100")


def test_cancel_releases_full_reservation_once() -> None:
    orders = service()
    order = orders.place(
        instrument_id="binance:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.1"),
        limit_price=Decimal("50000"),
    )

    canceled = orders.cancel(order.order_id)
    assert canceled.status is OrderStatus.CANCELED
    assert orders.ledger.balance("USDT").available == Decimal("10000")
    assert orders.ledger.balance("USDT").locked == 0

    with pytest.raises(InvalidOrderTransitionError):
        orders.cancel(order.order_id)


def test_account_cannot_place_order_for_another_exchange() -> None:
    orders = service()

    with pytest.raises(ValueError, match="does not match"):
        orders.place(
            instrument_id="okx:SPOT:BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.1"),
            limit_price=Decimal("50000"),
        )


def test_order_numeric_inputs_must_be_decimal() -> None:
    orders = service()

    with pytest.raises(TypeError, match="Decimal"):
        orders.place(
            instrument_id="binance:SPOT:BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.1,  # type: ignore[arg-type]
            limit_price=Decimal("50000"),
        )


def test_limit_buy_reserves_maximum_maker_or_taker_fee() -> None:
    orders = service()
    order = orders.place(
        instrument_id="binance:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.1"),
        limit_price=Decimal("50000"),
        fee_schedule=FeeSchedule(
            schedule_id="MOCK:v1",
            maker_rate=Decimal("0.0005"),
            taker_rate=Decimal("0.001"),
        ),
    )

    assert order.fee_schedule_id == "MOCK:v1"
    assert order.reserved_fee_rate == Decimal("0.001")
    assert order.reserved_amount == Decimal("5005.0000")


def test_order_records_submission_entry_time_and_deterministic_sequence() -> None:
    clock = ManualTime(1_000)
    orders = OrderService(create_paper_account(ExchangeId.BINANCE), clock=clock)
    first = orders.place(
        instrument_id="binance:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.01"),
        limit_price=Decimal("100"),
    )
    second = orders.place(
        instrument_id="binance:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.01"),
        limit_price=Decimal("100"),
    )

    assert first.submitted_ts_ms == 1_000
    assert first.market_entry_ts_ms is None
    assert first.order_sequence == 1
    assert second.order_sequence == 2

    clock.value = 1_100
    entered = orders.enter_market(first.order_id)
    assert entered.market_entry_ts_ms == 1_100


def test_market_entry_cannot_precede_submission_or_repeat() -> None:
    clock = ManualTime(1_000)
    orders = OrderService(create_paper_account(ExchangeId.BINANCE), clock=clock)
    order = orders.place(
        instrument_id="binance:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.01"),
        limit_price=Decimal("100"),
    )

    with pytest.raises(ValueError, match="precede"):
        orders.enter_market(order.order_id, market_entry_ts_ms=999)
    orders.enter_market(order.order_id, market_entry_ts_ms=1_000)
    with pytest.raises(InvalidOrderTransitionError, match="already"):
        orders.enter_market(order.order_id, market_entry_ts_ms=1_001)
