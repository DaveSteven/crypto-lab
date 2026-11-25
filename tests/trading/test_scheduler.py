from decimal import Decimal

import pytest

from crypto_lab.models import ExchangeId
from crypto_lab.trading import (
    ExecutionLatency,
    ExecutionScheduler,
    LatencyPreset,
    ManualClock,
    OrderService,
    OrderSide,
    OrderStatus,
    OrderType,
    create_paper_account,
)


def setup_scheduler() -> tuple[ManualClock, OrderService, ExecutionScheduler]:
    clock = ManualClock(1_000)
    orders = OrderService(create_paper_account(ExchangeId.OKX), clock=clock)
    return clock, orders, ExecutionScheduler(orders, clock)


def place(orders: OrderService):
    return orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        market_reference_price=Decimal("100"),
        max_quote_budget=Decimal("100"),
    )


def test_pending_execution_metadata_and_not_due_before_schedule() -> None:
    clock, orders, scheduler = setup_scheduler()
    order = place(orders)

    pending = scheduler.schedule(
        order.order_id,
        latency=ExecutionLatency(preset=LatencyPreset.NORMAL),
        submission_quote_event_id="submission-book",
    )

    assert pending.status is OrderStatus.PENDING_EXECUTION
    assert pending.scheduled_execution_ts_ms == 1_100
    assert pending.configured_latency_ms == 100
    assert pending.submission_quote_event_id == "submission-book"
    assert scheduler.due() == ()
    clock.advance(99)
    assert scheduler.due() == ()


def test_scheduled_market_buy_requires_explicit_budget() -> None:
    _, orders, scheduler = setup_scheduler()
    order = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        market_reference_price=Decimal("100"),
    )

    with pytest.raises(ValueError, match="explicit maximum quote budget"):
        scheduler.schedule(
            order.order_id,
            latency=ExecutionLatency(preset=LatencyPreset.NORMAL),
        )

    assert orders.get(order.order_id).status is OrderStatus.OPEN


def test_zero_latency_still_uses_scheduler_flow() -> None:
    _, orders, scheduler = setup_scheduler()
    order = place(orders)
    scheduler.schedule(order.order_id, latency=ExecutionLatency(preset=LatencyPreset.IDEAL))
    seen: list[str] = []

    result = scheduler.run_due(lambda pending, _: seen.append(pending.order_id))

    assert seen == [order.order_id]
    assert result.executed_order_ids == (order.order_id,)
    assert scheduler.due() == ()


def test_same_schedule_uses_order_sequence() -> None:
    clock, orders, scheduler = setup_scheduler()
    first = place(orders)
    second = place(orders)
    latency = ExecutionLatency(preset=LatencyPreset.FAST)
    scheduler.schedule(second.order_id, latency=latency)
    scheduler.schedule(first.order_id, latency=latency)
    clock.advance(50)

    assert [item.order_id for item in scheduler.due()] == [first.order_id, second.order_id]


def test_cancel_pending_order_releases_funds_and_prevents_execution() -> None:
    clock, orders, scheduler = setup_scheduler()
    order = place(orders)
    scheduler.schedule(order.order_id, latency=ExecutionLatency(preset=LatencyPreset.FAST))

    canceled = scheduler.cancel(order.order_id)
    clock.advance(50)
    result = scheduler.run_due(lambda *_: pytest.fail("canceled order executed"))

    assert canceled.status is OrderStatus.CANCELED
    assert orders.ledger.balance("USDT").locked == 0
    assert result.executed_order_ids == ()


def test_duplicate_schedule_and_execution_are_prevented() -> None:
    _, orders, scheduler = setup_scheduler()
    order = place(orders)
    latency = ExecutionLatency(preset=LatencyPreset.IDEAL)
    scheduler.schedule(order.order_id, latency=latency)
    with pytest.raises(ValueError, match="already"):
        scheduler.schedule(order.order_id, latency=latency)
    scheduler.run_due(lambda *_: None)
    with pytest.raises(ValueError, match="already"):
        scheduler.schedule(order.order_id, latency=latency)


def test_due_handler_records_actual_delay_and_market_entry() -> None:
    clock, orders, scheduler = setup_scheduler()
    order = place(orders)
    scheduler.schedule(
        order.order_id,
        latency=ExecutionLatency(preset=LatencyPreset.NORMAL),
    )
    clock.advance(125)

    def enter_market(pending, execution_ts_ms: int) -> None:
        orders.record_scheduled_execution(
            pending.order_id,
            executed_ts_ms=execution_ts_ms,
            execution_quote_event_id="execution-book",
        )
        orders.enter_market(pending.order_id, market_entry_ts_ms=execution_ts_ms)

    scheduler.run_due(enter_market)
    entered = orders.get(order.order_id)

    assert entered.status is OrderStatus.OPEN
    assert entered.executed_ts_ms == 1_125
    assert entered.actual_simulated_delay_ms == 125
    assert entered.scheduler_lag_ms == 25
    assert entered.execution_quote_event_id == "execution-book"
    assert entered.market_entry_ts_ms == 1_125
