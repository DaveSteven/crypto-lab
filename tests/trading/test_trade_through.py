from decimal import Decimal

import pytest

from crypto_lab.models import (
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketEventEnvelope,
    Trade,
    TradeSide,
    TransportType,
)
from crypto_lab.trading import (
    ExecutionSimulator,
    FeeSchedule,
    InsufficientBalanceError,
    LiquidityRole,
    OrderService,
    OrderSide,
    OrderStatus,
    OrderType,
    TradeProcessingStatus,
    TradeThroughEngine,
    create_paper_account,
)

INSTRUMENT = "okx:SPOT:BTC/USDT"
FEES = FeeSchedule(
    schedule_id="MOCK:v1",
    maker_rate=Decimal("0.001"),
    taker_rate=Decimal("0.002"),
)


class ManualTime:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def trade_event(
    event_id: str,
    *,
    price: str,
    quantity: str,
    side: TradeSide,
    trade_id: str | None = None,
    exchange_ts_ms: int | None = 2_000,
    received_ts_ms: int = 2_001,
    quality: DataQualityStatus = DataQualityStatus.VALID,
    instrument_id: str = INSTRUMENT,
) -> MarketEventEnvelope[Trade]:
    return MarketEventEnvelope[Trade](
        event_id=event_id,
        event_type="TRADE",
        exchange_id=ExchangeId.OKX,
        instrument_id=instrument_id,
        source_type=DataSourceType.MOCK,
        transport=TransportType.FILE,
        exchange_ts_ms=exchange_ts_ms,
        received_ts_ms=received_ts_ms,
        quality_status=quality,
        payload=Trade(
            trade_id=trade_id,
            price=price,
            quantity=quantity,
            side=side,
        ),
    )


def buy_engine() -> tuple[OrderService, TradeThroughEngine, ManualTime]:
    clock = ManualTime(1_000)
    orders = OrderService(create_paper_account(ExchangeId.OKX), clock=clock)
    engine = TradeThroughEngine(
        simulation_environment_id="run-1",
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        simulator=ExecutionSimulator(orders),
        fee_schedule=FEES,
        max_trade_age_ms=2_000,
    )
    return orders, engine, clock


def place_buy(
    orders: OrderService,
    clock: ManualTime,
    *,
    limit: str,
    quantity: str,
    entry_ts_ms: int,
    fees: FeeSchedule = FEES,
):
    clock.value = min(clock.value, entry_ts_ms)
    order = orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal(quantity),
        limit_price=Decimal(limit),
        fee_schedule=fees,
    )
    return orders.enter_market(order.order_id, market_entry_ts_ms=entry_ts_ms)


def test_equal_limit_does_not_trigger_but_strict_trade_through_does() -> None:
    orders, engine, clock = buy_engine()
    order = place_buy(orders, clock, limit="100", quantity="2", entry_ts_ms=1_100)

    touched = engine.process_trade(
        trade_event("trade-1", price="100", quantity="2", side=TradeSide.SELL),
        observed_ts_ms=2_001,
    )
    crossed = engine.process_trade(
        trade_event(
            "trade-2",
            price="99",
            quantity="2",
            side=TradeSide.SELL,
            exchange_ts_ms=2_100,
            received_ts_ms=2_101,
        ),
        observed_ts_ms=2_101,
    )

    assert touched.allocations == ()
    assert len(crossed.allocations) == 1
    execution = crossed.allocations[0].execution
    assert execution.price == Decimal("100")
    assert execution.price != Decimal("99")
    assert execution.liquidity_role is LiquidityRole.MAKER
    assert execution.fee_amount == Decimal("0.2")
    assert orders.get(order.order_id).status is OrderStatus.FILLED


@pytest.mark.parametrize("side", [TradeSide.BUY, TradeSide.UNKNOWN])
def test_buy_order_ignores_wrong_or_unknown_aggressor_side(side: TradeSide) -> None:
    orders, engine, clock = buy_engine()
    order = place_buy(orders, clock, limit="100", quantity="2", entry_ts_ms=1_100)

    result = engine.process_trade(
        trade_event("trade-1", price="99", quantity="2", side=side),
        observed_ts_ms=2_001,
    )

    assert result.allocations == ()
    assert orders.get(order.order_id).filled_quantity == 0


def test_trade_quantity_is_shared_by_price_priority() -> None:
    orders, engine, clock = buy_engine()
    lower = place_buy(orders, clock, limit="100", quantity="3", entry_ts_ms=1_100)
    higher = place_buy(orders, clock, limit="101", quantity="3", entry_ts_ms=1_200)

    result = engine.process_trade(
        trade_event("trade-1", price="99", quantity="4", side=TradeSide.SELL),
        observed_ts_ms=2_001,
    )

    assert [allocation.order_id for allocation in result.allocations] == [
        higher.order_id,
        lower.order_id,
    ]
    assert [allocation.quantity for allocation in result.allocations] == [
        Decimal("3"),
        Decimal("1"),
    ]
    assert orders.get(higher.order_id).status is OrderStatus.FILLED
    assert orders.get(lower.order_id).status is OrderStatus.PARTIALLY_FILLED
    assert result.remaining_trade_quantity == 0


def test_same_price_uses_entry_time_then_order_sequence() -> None:
    orders, engine, clock = buy_engine()
    early = place_buy(orders, clock, limit="100", quantity="1", entry_ts_ms=1_100)
    same_time_first = place_buy(orders, clock, limit="100", quantity="1", entry_ts_ms=1_200)
    same_time_second = place_buy(orders, clock, limit="100", quantity="1", entry_ts_ms=1_200)

    result = engine.process_trade(
        trade_event("trade-1", price="99", quantity="2", side=TradeSide.SELL),
        observed_ts_ms=2_001,
    )

    assert [allocation.order_id for allocation in result.allocations] == [
        early.order_id,
        same_time_first.order_id,
    ]
    assert orders.get(same_time_second.order_id).filled_quantity == 0


def test_partial_fill_keeps_remaining_reservation_and_cancel_releases_it() -> None:
    orders, engine, clock = buy_engine()
    order = place_buy(orders, clock, limit="100", quantity="3", entry_ts_ms=1_100)

    result = engine.process_trade(
        trade_event("trade-1", price="99", quantity="1", side=TradeSide.SELL),
        observed_ts_ms=2_001,
    )

    assert result.allocations[0].quantity == Decimal("1")
    assert orders.get(order.order_id).status is OrderStatus.PARTIALLY_FILLED
    assert orders.ledger.balance("USDT").locked == Decimal("200.500")
    orders.cancel(order.order_id)
    assert orders.ledger.balance("USDT").locked == 0


def test_duplicate_trade_id_is_not_consumed_twice() -> None:
    orders, engine, clock = buy_engine()
    order = place_buy(orders, clock, limit="100", quantity="3", entry_ts_ms=1_100)
    first = trade_event(
        "event-1",
        trade_id="exchange-trade-1",
        price="99",
        quantity="1",
        side=TradeSide.SELL,
    )
    duplicate = first.model_copy(update={"event_id": "event-2"})

    engine.process_trade(first, observed_ts_ms=2_001)
    result = engine.process_trade(duplicate, observed_ts_ms=2_001)

    assert result.status is TradeProcessingStatus.DUPLICATE
    assert result.allocations == ()
    assert orders.get(order.order_id).filled_quantity == Decimal("1")


@pytest.mark.parametrize(
    ("exchange_ts_ms", "received_ts_ms"),
    [(1_100, 2_001), (2_000, 1_100)],
)
def test_trade_not_strictly_after_market_entry_cannot_fill(
    exchange_ts_ms: int, received_ts_ms: int
) -> None:
    orders, engine, clock = buy_engine()
    order = place_buy(orders, clock, limit="100", quantity="1", entry_ts_ms=1_100)

    result = engine.process_trade(
        trade_event(
            "trade-1",
            price="99",
            quantity="1",
            side=TradeSide.SELL,
            exchange_ts_ms=exchange_ts_ms,
            received_ts_ms=received_ts_ms,
        ),
        observed_ts_ms=2_001,
    )

    assert result.allocations == ()
    assert orders.get(order.order_id).filled_quantity == 0


def test_missing_exchange_time_is_ignored_conservatively() -> None:
    orders, engine, clock = buy_engine()
    order = place_buy(orders, clock, limit="100", quantity="1", entry_ts_ms=1_100)

    result = engine.process_trade(
        trade_event(
            "trade-1",
            price="99",
            quantity="1",
            side=TradeSide.SELL,
            exchange_ts_ms=None,
        ),
        observed_ts_ms=2_001,
    )

    assert result.status is TradeProcessingStatus.IGNORED
    assert orders.get(order.order_id).filled_quantity == 0


@pytest.mark.parametrize(
    ("event", "observed_ts_ms"),
    [
        (
            trade_event(
                "invalid-quality",
                price="99",
                quantity="1",
                side=TradeSide.SELL,
                quality=DataQualityStatus.INVALID,
            ),
            2_001,
        ),
        (
            trade_event("stale", price="99", quantity="1", side=TradeSide.SELL),
            4_002,
        ),
        (
            trade_event(
                "future",
                price="99",
                quantity="1",
                side=TradeSide.SELL,
                received_ts_ms=2_100,
            ),
            2_001,
        ),
        (
            trade_event(
                "wrong-market",
                price="99",
                quantity="1",
                side=TradeSide.SELL,
                instrument_id="okx:SPOT:ETH/USDT",
            ),
            2_001,
        ),
    ],
)
def test_invalid_stale_future_or_wrong_market_trade_is_ignored(
    event: MarketEventEnvelope[Trade], observed_ts_ms: int
) -> None:
    orders, engine, clock = buy_engine()
    order = place_buy(orders, clock, limit="100", quantity="1", entry_ts_ms=1_100)

    result = engine.process_trade(event, observed_ts_ms=observed_ts_ms)

    assert result.status is TradeProcessingStatus.IGNORED
    assert result.allocations == ()
    assert orders.get(order.order_id).filled_quantity == 0


def test_canceled_order_cannot_fill() -> None:
    orders, engine, clock = buy_engine()
    order = place_buy(orders, clock, limit="100", quantity="1", entry_ts_ms=1_100)
    orders.cancel(order.order_id)

    result = engine.process_trade(
        trade_event("trade-1", price="99", quantity="1", side=TradeSide.SELL),
        observed_ts_ms=2_001,
    )

    assert result.allocations == ()
    assert orders.get(order.order_id).status is OrderStatus.CANCELED


def test_settlement_failure_does_not_consume_trade_quantity() -> None:
    safe = FeeSchedule(
        schedule_id="SAME-ID",
        maker_rate=Decimal("0"),
        taker_rate=Decimal("0"),
    )
    expensive = FeeSchedule(
        schedule_id="SAME-ID",
        maker_rate=Decimal("0.01"),
        taker_rate=Decimal("0.01"),
    )
    orders, _, clock = buy_engine()
    order = place_buy(
        orders,
        clock,
        limit="100",
        quantity="1",
        entry_ts_ms=1_100,
        fees=safe,
    )
    simulator = ExecutionSimulator(orders)
    engine = TradeThroughEngine(
        simulation_environment_id="run-1",
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        simulator=simulator,
        fee_schedule=expensive,
        max_trade_age_ms=2_000,
    )
    event = trade_event("trade-1", price="99", quantity="1", side=TradeSide.SELL)
    entries_before = orders.ledger.entries

    with pytest.raises(InsufficientBalanceError):
        engine.process_trade(event, observed_ts_ms=2_001)

    assert orders.get(order.order_id).filled_quantity == 0
    assert orders.ledger.entries == entries_before
    engine.fee_schedule = safe
    retried = engine.process_trade(event, observed_ts_ms=2_001)
    assert retried.allocations[0].quantity == Decimal("1")


def test_older_trade_after_newer_event_is_rejected() -> None:
    orders, engine, clock = buy_engine()
    order = place_buy(orders, clock, limit="100", quantity="2", entry_ts_ms=1_100)
    engine.process_trade(
        trade_event(
            "newer",
            price="99",
            quantity="1",
            side=TradeSide.SELL,
            exchange_ts_ms=2_100,
            received_ts_ms=2_101,
        ),
        observed_ts_ms=2_101,
    )

    result = engine.process_trade(
        trade_event("older", price="99", quantity="1", side=TradeSide.SELL),
        observed_ts_ms=2_102,
    )

    assert result.status is TradeProcessingStatus.OUT_OF_ORDER
    assert orders.get(order.order_id).filled_quantity == Decimal("1")


def test_sell_order_requires_active_buy_trade_strictly_above_limit() -> None:
    clock = ManualTime(1_000)
    ledger = create_paper_account(
        ExchangeId.OKX,
        initial_asset="BTC",
        initial_amount=Decimal("2"),
    )
    orders = OrderService(ledger, clock=clock)
    order = orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("2"),
        limit_price=Decimal("100"),
        fee_schedule=FEES,
    )
    orders.enter_market(order.order_id, market_entry_ts_ms=1_100)
    engine = TradeThroughEngine(
        simulation_environment_id="run-1",
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        simulator=ExecutionSimulator(orders),
        fee_schedule=FEES,
        max_trade_age_ms=2_000,
    )

    result = engine.process_trade(
        trade_event("trade-1", price="101", quantity="2", side=TradeSide.BUY),
        observed_ts_ms=2_001,
    )

    assert result.allocations[0].execution.price == Decimal("100")
    assert orders.get(order.order_id).status is OrderStatus.FILLED


def _replay_outcome() -> tuple[object, ...]:
    orders, engine, clock = buy_engine()
    lower = place_buy(orders, clock, limit="100", quantity="2", entry_ts_ms=1_100)
    higher = place_buy(orders, clock, limit="101", quantity="1", entry_ts_ms=1_200)
    result = engine.process_trade(
        trade_event(
            "stable-event-id",
            trade_id="stable-trade-id",
            price="99",
            quantity="2",
            side=TradeSide.SELL,
        ),
        observed_ts_ms=2_001,
    )
    return (
        tuple(
            (
                allocation.quantity,
                allocation.execution.price,
                allocation.execution.fee_amount,
                allocation.execution.liquidity_role,
            )
            for allocation in result.allocations
        ),
        orders.get(lower.order_id).filled_quantity,
        orders.get(higher.order_id).filled_quantity,
        orders.ledger.balance("USDT"),
    )


def test_event_replay_produces_deterministic_financial_outcome() -> None:
    assert _replay_outcome() == _replay_outcome()
