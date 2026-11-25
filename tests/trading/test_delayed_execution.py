from decimal import Decimal

from crypto_lab.market_data import OrderBookMarketState
from crypto_lab.models import (
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketEventEnvelope,
    OrderBookSnapshot,
    PriceLevel,
    TransportType,
)
from crypto_lab.trading import (
    ExecutionLatency,
    ExecutionScheduler,
    ExecutionSimulator,
    FeeSchedule,
    LatencyPreset,
    LimitOrderExecutionService,
    ManualClock,
    MarketRules,
    OrderBookExecutionService,
    OrderService,
    OrderSide,
    OrderStatus,
    OrderType,
    ScheduledOrderExecutor,
    SimulatedLiquidityView,
    create_paper_account,
)

INSTRUMENT = "okx:SPOT:BTC/USDT"
FEES = FeeSchedule(
    schedule_id="OKX:MOCK",
    maker_rate=Decimal("0.001"),
    taker_rate=Decimal("0.01"),
)
RULES = MarketRules(
    rules_id="OKX:MOCK",
    price_increment=Decimal("1"),
    quantity_increment=Decimal("1"),
    min_quantity=Decimal("1"),
    min_notional=Decimal("10"),
)


def snapshot(event_id: str, *, ask: str, received_ts_ms: int):
    ask_price = Decimal(ask)
    return MarketEventEnvelope[OrderBookSnapshot](
        event_id=event_id,
        event_type="ORDER_BOOK_SNAPSHOT",
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        source_type=DataSourceType.MOCK,
        transport=TransportType.FILE,
        exchange_ts_ms=received_ts_ms - 1,
        received_ts_ms=received_ts_ms,
        quality_status=DataQualityStatus.VALID,
        payload=OrderBookSnapshot(
            bids=(PriceLevel(price=ask_price - 1, quantity="10"),),
            asks=(PriceLevel(price=ask_price, quantity="10"),),
            depth=10,
            sequence_id=event_id,
            synchronized=True,
        ),
    )


def context(rules: MarketRules = RULES):
    clock = ManualClock(1_000)
    orders = OrderService(create_paper_account(ExchangeId.OKX), clock=clock)
    simulator = ExecutionSimulator(orders)
    state = OrderBookMarketState()
    liquidity = SimulatedLiquidityView("delayed-run")
    executor = ScheduledOrderExecutor(
        orders=orders,
        market_state=state,
        market_execution=OrderBookExecutionService(state, simulator, liquidity),
        limit_execution=LimitOrderExecutionService(state, simulator, liquidity),
    )
    scheduler = ExecutionScheduler(orders, clock)
    return clock, orders, state, liquidity, scheduler, executor, rules


def register(scheduler, executor, order_id: str, rules: MarketRules = RULES) -> None:
    scheduler.schedule(
        order_id,
        latency=ExecutionLatency(preset=LatencyPreset.NORMAL),
        submission_quote_event_id="submission-book",
    )
    executor.register(
        order_id,
        exchange_id=ExchangeId.OKX,
        max_book_age_ms=500,
        fee_schedule=FEES,
        market_rules=rules,
        consumption_id=f"consume-{order_id}",
    )


def test_due_market_buy_uses_new_price_and_records_timing() -> None:
    clock, orders, state, _, scheduler, executor, _ = context()
    order = orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("2"),
        market_reference_price=Decimal("100"),
        fee_schedule=FEES,
    )
    register(scheduler, executor, order.order_id)
    state.apply_snapshot(snapshot("execution-book", ask="90", received_ts_ms=1_050))
    clock.advance(100)

    scheduler.run_due(executor)

    updated = orders.get(order.order_id)
    assert updated.status is OrderStatus.FILLED
    assert updated.average_fill_price == Decimal("90")
    assert updated.executed_ts_ms == 1_100
    assert updated.market_entry_ts_ms == 1_100
    assert updated.actual_simulated_delay_ms == 100
    assert updated.submission_quote_event_id == "submission-book"
    assert updated.execution_quote_event_id == "execution-book"
    assert executor.outcome(order.order_id).outcome == "FILLED"


def test_market_price_rise_partially_fills_within_budget_then_cancels() -> None:
    clock, orders, state, _, scheduler, executor, _ = context()
    order = orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("2"),
        market_reference_price=Decimal("100"),
        fee_schedule=FEES,
    )
    register(scheduler, executor, order.order_id)
    state.apply_snapshot(snapshot("higher-book", ask="110", received_ts_ms=1_050))
    clock.advance(100)

    scheduler.run_due(executor)

    updated = orders.get(order.order_id)
    assert updated.status is OrderStatus.CANCELED
    assert updated.filled_quantity == Decimal("1")
    assert orders.ledger.balance("USDT").locked == 0
    assert executor.outcome(order.order_id).outcome == "PARTIAL_CANCELED"


def test_gtc_limit_remainder_enters_resting_state_after_delay() -> None:
    clock, orders, state, _, scheduler, executor, _ = context()
    order = orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("2"),
        limit_price=Decimal("100"),
        fee_schedule=FEES,
    )
    register(scheduler, executor, order.order_id)
    state.apply_snapshot(snapshot("limit-book", ask="101", received_ts_ms=1_050))
    clock.advance(100)

    scheduler.run_due(executor)

    updated = orders.get(order.order_id)
    assert updated.status is OrderStatus.OPEN
    assert updated.market_entry_ts_ms == 1_100
    assert orders.ledger.balance("USDT").locked == Decimal("202.00")
    assert executor.outcome(order.order_id).outcome == "RESTING"


def test_marketable_gtc_limit_partially_fills_then_rests() -> None:
    clock, orders, state, _, scheduler, executor, _ = context()
    order = orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("2"),
        limit_price=Decimal("100"),
        fee_schedule=FEES,
    )
    register(scheduler, executor, order.order_id)
    event = snapshot("partial-limit-book", ask="99", received_ts_ms=1_050)
    event = event.model_copy(
        update={
            "payload": event.payload.model_copy(
                update={
                    "asks": (
                        PriceLevel(price="99", quantity="1"),
                        PriceLevel(price="101", quantity="10"),
                    )
                }
            )
        }
    )
    state.apply_snapshot(event)
    clock.advance(100)

    scheduler.run_due(executor)

    updated = orders.get(order.order_id)
    assert updated.status is OrderStatus.PARTIALLY_FILLED
    assert updated.filled_quantity == Decimal("1")
    assert orders.ledger.balance("USDT").locked == Decimal("102.01")
    assert executor.outcome(order.order_id).outcome == "RESTING"


def test_future_or_stale_book_rejects_and_releases_pending_order() -> None:
    clock, orders, state, _, scheduler, executor, _ = context()
    order = orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        market_reference_price=Decimal("100"),
        fee_schedule=FEES,
    )
    register(scheduler, executor, order.order_id)
    state.apply_snapshot(snapshot("future-book", ask="90", received_ts_ms=1_101))
    clock.advance(100)

    scheduler.run_due(executor)

    updated = orders.get(order.order_id)
    assert updated.status is OrderStatus.REJECTED
    assert updated.termination_reason == "MARKET_DATA_UNAVAILABLE"
    assert updated.execution_quote_event_id is None
    assert orders.ledger.balance("USDT").locked == 0
    assert "after decision" in executor.outcome(order.order_id).reason


def test_stale_book_rejects_without_execution() -> None:
    clock, orders, state, _, scheduler, executor, _ = context()
    order = orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        market_reference_price=Decimal("100"),
        fee_schedule=FEES,
    )
    register(scheduler, executor, order.order_id)
    state.apply_snapshot(snapshot("stale-book", ask="100", received_ts_ms=500))
    clock.advance(100)

    scheduler.run_due(executor)

    assert orders.get(order.order_id).status is OrderStatus.REJECTED
    assert "stale" in executor.outcome(order.order_id).reason


def test_settlement_validation_failure_does_not_consume_liquidity() -> None:
    incompatible_rules = RULES.model_copy(update={"price_increment": Decimal("3")})
    clock, orders, state, liquidity, scheduler, executor, _ = context(incompatible_rules)
    order = orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        market_reference_price=Decimal("100"),
        fee_schedule=FEES,
    )
    register(scheduler, executor, order.order_id, incompatible_rules)
    state.apply_snapshot(snapshot("bad-rules-book", ask="100", received_ts_ms=1_050))
    clock.advance(100)

    scheduler.run_due(executor)

    assert orders.get(order.order_id).status is OrderStatus.REJECTED
    assert executor.outcome(order.order_id).outcome == "FAILED"
    assert liquidity.available_book().asks[0].quantity == Decimal("10")
    assert orders.ledger.balance("USDT").locked == 0
