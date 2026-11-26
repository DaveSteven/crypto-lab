from __future__ import annotations

import os
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, select

from crypto_lab.market_data import OrderBookView
from crypto_lab.models import DataQualityStatus, ExchangeId, PriceLevel
from crypto_lab.persistence import PersistenceError, PostgresUnitOfWork, schema
from crypto_lab.trading import (
    DeterministicIdGenerator,
    ExecutionLatency,
    ExecutionScheduler,
    ExecutionSimulator,
    LatencyPreset,
    ManualClock,
    OrderService,
    OrderSide,
    OrderType,
    PortfolioEngine,
    SimulatedLiquidityView,
    create_paper_account,
    match_market_order,
)


@pytest.fixture(scope="module")
def database_url() -> str:
    value = os.getenv("CRYPTO_LAB_TEST_DATABASE_URL")
    if not value:
        pytest.skip("CRYPTO_LAB_TEST_DATABASE_URL is not configured")
    return value


@pytest.fixture
def engine(database_url: str):
    result = create_engine(database_url)
    with result.begin() as connection:
        for table in reversed(schema.metadata.sorted_tables):
            connection.execute(table.delete())
    yield result
    result.dispose()


def trading_state(namespace: str = "postgres-test"):
    ids = DeterministicIdGenerator(namespace)
    clock = ManualClock(1_000)
    ledger = create_paper_account(
        ExchangeId.OKX,
        id_generator=ids,
        clock=clock,
    )
    orders = OrderService(ledger, clock=clock)
    portfolio = PortfolioEngine()
    simulator = ExecutionSimulator(orders, portfolio=portfolio)
    order = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
        estimated_buy_fee_rate=Decimal("0.01"),
    )
    simulator.execute(
        order.order_id,
        price=Decimal("100"),
        quantity=Decimal("1"),
        fee_rate=Decimal("0.01"),
    )
    return ids, clock, ledger, orders, portfolio, simulator


def test_initial_migration_created_expected_postgresql_tables(engine) -> None:
    assert set(inspect(engine).get_table_names()) >= set(schema.metadata.tables)


def test_trading_state_round_trips_and_projections_rebuild(engine) -> None:
    ids, clock, ledger, orders, portfolio, simulator = trading_state()
    uow = PostgresUnitOfWork(engine)
    with uow.bootstrap() as store:
        store.create_environment(
            environment_id="environment-1",
            name="Integration Test",
            id_namespace=ids.namespace,
            created_ts_ms=clock.now_utc_ms(),
        )
    with uow.transaction("environment-1") as store:
        store.persist_trading_state(
            environment_id="environment-1",
            ledger=ledger,
            orders=orders,
            executions=simulator.executions(),
            portfolio=portfolio,
        )

    restore_ids = DeterministicIdGenerator("environment-1-restore")
    restore_clock = ManualClock(2_000)
    with uow.transaction("environment-1") as store:
        restored_ledger = store.restore_account_ledger(
            account_id=ledger.account.account_id,
            id_generator=restore_ids,
            clock=restore_clock,
        )
        restored_orders = store.restore_orders(restored_ledger, "environment-1")
        restored_executions = store.restore_executions("environment-1")
        restored_portfolio = store.restore_portfolio("environment-1")

    assert restored_ledger.entries == ledger.entries
    assert restored_ledger.balances() == ledger.balances()
    assert restored_orders.orders() == orders.orders()
    assert restored_executions == simulator.executions()
    assert restored_portfolio.positions() == portfolio.positions()


def test_database_transaction_rolls_back_event_marker_on_failure(engine) -> None:
    uow = PostgresUnitOfWork(engine)
    with uow.bootstrap() as store:
        store.create_environment(
            environment_id="environment-rollback",
            name="Rollback Test",
            id_namespace="rollback-test",
            created_ts_ms=1_000,
        )

    with (
        pytest.raises(RuntimeError, match="injected"),
        uow.transaction("environment-rollback") as store,
    ):
        store.session.execute(
            schema.simulation_events.insert().values(
                event_id="event-1",
                environment_id="environment-rollback",
                event_kind="TRADE",
                event_ts_ms=1_000,
                arrival_sequence=1,
                payload_json={},
                status="PROCESSED",
            )
        )
        raise RuntimeError("injected transaction failure")

    with engine.connect() as connection:
        assert connection.execute(select(schema.simulation_events.c.event_id)).all() == []


def test_decimal_exceeding_database_scale_is_rejected_before_write(engine) -> None:
    ids, clock, ledger, orders, portfolio, simulator = trading_state("precision-test")
    invalid = orders.orders()[0].model_copy(
        update={"cumulative_fee": Decimal("0.0000000000000000000000001")}
    )
    orders.restore_state(({invalid.order_id: invalid}, 2))
    uow = PostgresUnitOfWork(engine)
    with uow.bootstrap() as store:
        store.create_environment(
            environment_id="environment-precision",
            name="Precision Test",
            id_namespace=ids.namespace,
            created_ts_ms=clock.now_utc_ms(),
        )

    with (
        pytest.raises(PersistenceError, match="NUMERIC"),
        uow.transaction("environment-precision") as store,
    ):
        store.persist_trading_state(
            environment_id="environment-precision",
            ledger=ledger,
            orders=orders,
            executions=simulator.executions(),
            portfolio=portfolio,
        )


def test_pending_scheduler_id_state_and_liquidity_restore(engine) -> None:
    ids = DeterministicIdGenerator("recovery-test")
    clock = ManualClock(1_000)
    ledger = create_paper_account(ExchangeId.OKX, id_generator=ids, clock=clock)
    orders = OrderService(ledger, clock=clock)
    portfolio = PortfolioEngine()
    order = orders.place(
        instrument_id="okx:SPOT:BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        market_reference_price=Decimal("100"),
        max_quote_budget=Decimal("101"),
    )
    scheduler = ExecutionScheduler(orders, clock)
    scheduler.schedule(
        order.order_id,
        latency=ExecutionLatency(preset=LatencyPreset.NORMAL),
    )
    book = OrderBookView(
        exchange_id=ExchangeId.OKX,
        instrument_id="okx:SPOT:BTC/USDT",
        bids=(PriceLevel(price="99", quantity="2"),),
        asks=(PriceLevel(price="100", quantity="2"),),
        depth=10,
        sequence_id="1",
        source_event_id="book-1",
        exchange_ts_ms=999,
        received_ts_ms=1_000,
        quality_status=DataQualityStatus.VALID,
        synchronized=True,
        source_connected=True,
    )
    liquidity = SimulatedLiquidityView("environment-recovery")
    liquidity.synchronize(book)
    plan = match_market_order(
        liquidity.available_book(),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        submission_reference_price=Decimal("100"),
    )
    liquidity.consume(plan, consumption_id="consumption-1")
    uow = PostgresUnitOfWork(engine)
    with uow.bootstrap() as store:
        store.create_environment(
            environment_id="environment-recovery",
            name="Recovery Test",
            id_namespace=ids.namespace,
            created_ts_ms=clock.now_utc_ms(),
        )
    with uow.transaction("environment-recovery") as store:
        store.persist_trading_state(
            environment_id="environment-recovery",
            ledger=ledger,
            orders=orders,
            executions=(),
            portfolio=portfolio,
            scheduler=scheduler,
        )
        store.persist_id_generator("environment-recovery", ids)
        store.persist_liquidity(
            environment_id="environment-recovery",
            liquidity=liquidity,
            updated_ts_ms=clock.now_utc_ms(),
        )

    expected_next_order_id = ids.next_id("order")
    with uow.transaction("environment-recovery") as store:
        restored_ids = store.restore_id_generator("environment-recovery", ids.namespace)
        restored_ledger = store.restore_account_ledger(
            account_id=ledger.account.account_id,
            id_generator=restored_ids,
            clock=clock,
        )
        restored_orders = store.restore_orders(restored_ledger, "environment-recovery")
        restored_scheduler = store.restore_scheduler(
            environment_id="environment-recovery",
            orders=restored_orders,
            clock=clock,
        )
        restored_liquidity = store.restore_liquidity(
            environment_id="environment-recovery",
            exchange_id=ExchangeId.OKX,
            instrument_id="okx:SPOT:BTC/USDT",
        )

    assert restored_ids.next_id("order") == expected_next_order_id
    assert restored_scheduler.snapshot_state() == scheduler.snapshot_state()
    assert restored_liquidity.snapshot_state() == liquidity.snapshot_state()


def test_typed_events_recover_in_order_and_complete_idempotently(engine) -> None:
    uow = PostgresUnitOfWork(engine)
    with uow.bootstrap() as store:
        store.create_environment(
            environment_id="environment-events",
            name="Event Test",
            id_namespace="event-test",
            created_ts_ms=900,
        )
    with uow.transaction("environment-events") as store:
        second_sequence = store.enqueue_event(
            environment_id="environment-events",
            event_id="event-2",
            event_kind="SCHEDULED_EXECUTION",
            event_ts_ms=1_100,
            payload={"order_id": "order-1"},
        )
        first_sequence = store.enqueue_event(
            environment_id="environment-events",
            event_id="event-1",
            event_kind="MARKET_DATA",
            event_ts_ms=1_000,
            payload={"market_event_id": "book-1"},
        )
        duplicate_sequence = store.enqueue_event(
            environment_id="environment-events",
            event_id="event-1",
            event_kind="MARKET_DATA",
            event_ts_ms=1_000,
            payload={"market_event_id": "book-1"},
        )

    assert (first_sequence, second_sequence, duplicate_sequence) == (2, 1, 2)
    with uow.transaction("environment-events") as store:
        pending = store.pending_events("environment-events")
        store.complete_event(event_id="event-1", result={"accepted": True}, processed_ts_ms=1_000)
        assert store.record_processed_market_event(
            environment_id="environment-events",
            source_event_key="okx:BTC-USDT:trade:1",
            event_type="TRADE",
            processed_ts_ms=1_000,
            result={"fills": 1},
        )
        assert not store.record_processed_market_event(
            environment_id="environment-events",
            source_event_key="okx:BTC-USDT:trade:1",
            event_type="TRADE",
            processed_ts_ms=1_000,
            result={"fills": 1},
        )

    assert [row["event_id"] for row in pending] == ["event-1", "event-2"]
    with uow.transaction("environment-events") as store:
        assert [row["event_id"] for row in store.pending_events("environment-events")] == [
            "event-2"
        ]
        with pytest.raises(PersistenceError, match="already completed"):
            store.complete_event(
                event_id="event-1",
                result={"accepted": True},
                processed_ts_ms=1_001,
            )
