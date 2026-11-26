"""Dispatcher tests using an in-memory fake store and real trading objects."""

import contextlib
from decimal import Decimal

from crypto_lab.market_data import OrderBookView
from crypto_lab.models import (
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketEventEnvelope,
    PriceLevel,
    Trade,
    TradeSide,
    TransportType,
)
from crypto_lab.realtime import EnvironmentMarketDispatcher
from crypto_lab.trading import (
    ExecutionLatency,
    ExecutionScheduler,
    FeeSchedule,
    LatencyPreset,
    ManualClock,
    MarketRules,
    OrderService,
    OrderSide,
    OrderType,
    PortfolioEngine,
    SimulatedLiquidityView,
    create_paper_account,
)
from crypto_lab.trading.identity import DeterministicIdGenerator

INSTRUMENT = "okx:SPOT:BTC/USDT"
FEES = FeeSchedule(
    schedule_id="phase1-default-v1",
    maker_rate=Decimal("0.001"),
    taker_rate=Decimal("0.001"),
)
RULES = MarketRules(
    rules_id="OKX:TEST",
    price_increment=Decimal("0.1"),
    quantity_increment=Decimal("0.00000001"),
    min_quantity=Decimal("0.00001"),
    min_notional=None,
)


class World:
    """Shared in-memory stand-in for PostgreSQL persistence."""

    def __init__(self) -> None:
        self.clock = ManualClock(1_000)
        self.ledger = create_paper_account(
            ExchangeId.OKX,
            initial_amount=Decimal("10000"),
            id_generator=DeterministicIdGenerator("env-1"),
            clock=self.clock,
        )
        self.orders = OrderService(self.ledger, clock=self.clock)
        self.executions: tuple = ()
        self.liquidity: dict[str, tuple] = {}
        self.processed: set[str] = set()
        self.processed_results: dict[str, dict] = {}
        self.staged: list = []
        self.state_version = 0
        self.scheduled: dict[str, tuple[int, int]] = {}
        self.account_id = self.ledger.account.account_id


class FakeStore:
    def __init__(self, world: World) -> None:
        self.world = world
        self.session = None

    def record_processed_market_event(
        self,
        *,
        environment_id: str,
        source_event_key: str,
        event_type: str,
        processed_ts_ms: int,
        result: dict,
    ) -> bool:
        if source_event_key in self.world.processed:
            return False
        self.world.processed.add(source_event_key)
        self.world.processed_results[source_event_key] = result
        return True

    def load_environment(self, environment_id: str) -> dict:
        return {"id_namespace": environment_id}

    def restore_id_generator(self, environment_id: str, namespace: str):
        return DeterministicIdGenerator(namespace)

    def restore_account_ledger(self, *, account_id: str, id_generator, clock):
        return self.world.ledger

    def restore_orders(self, ledger, environment_id: str):
        return self.world.orders

    def restore_executions(self, environment_id: str):
        return self.world.executions

    def restore_scheduler(self, *, environment_id, orders, clock):
        from crypto_lab.trading import ScheduledExecution

        scheduler = ExecutionScheduler(orders, clock)
        pending = {
            order_id: ScheduledExecution(
                order_id=order_id,
                scheduled_execution_ts_ms=ts,
                order_sequence=sequence,
            )
            for order_id, (ts, sequence) in self.world.scheduled.items()
        }
        scheduler.restore_state((pending, set()))
        return scheduler

    def restore_portfolio(self, environment_id: str):
        return PortfolioEngine(self.world.executions)

    def persist_trading_state(
        self, *, environment_id, ledger, orders, executions, portfolio, scheduler=None
    ):
        self.world.executions = executions
        if scheduler is not None:
            self.world.scheduled = {
                order_id: (item.scheduled_execution_ts_ms, item.order_sequence)
                for order_id, item in scheduler.snapshot_state()[0].items()
            }

    def persist_id_generator(self, environment_id, ids) -> None:
        return None

    def bump_state_version(self, environment_id: str, updated_ts_ms: int) -> int:
        self.world.state_version += 1
        return self.world.state_version

    def stage_execution_events(self, **kwargs) -> None:
        self.world.staged.append(kwargs)

    def persist_liquidity(self, *, environment_id, liquidity, updated_ts_ms) -> None:
        self.world.liquidity[environment_id] = liquidity.snapshot_state()

    def restore_liquidity_optimistic(self, *, environment_id, exchange_id, instrument_id):
        state = self.world.liquidity.get(environment_id)
        if state is None:
            return None
        liquidity = SimulatedLiquidityView(environment_id)
        liquidity.restore_state(state)
        return liquidity

    def due_schedule_groups(self, environment_id: str, now_ms: int):
        groups: dict[str, list[str]] = {}
        for order_id, (ts, _sequence) in sorted(
            self.world.scheduled.items(), key=lambda item: (item[1][0], item[1][1])
        ):
            if ts <= now_ms:
                groups.setdefault(self.world.account_id, []).append(order_id)
        return list(groups.items())

    def last_processed_trade_ordering_key(self, environment_id: str):
        keys = [
            result["ordering_key"]
            for result in self.world.processed_results.values()
            if "ordering_key" in result
        ]
        if not keys:
            return None
        return tuple(keys[-1])

    def primary_account_id(self, environment_id: str):
        return self.world.account_id


class FakeUnitOfWork:
    def __init__(self, world: World) -> None:
        self.world = world

    @contextlib.contextmanager
    def transaction(self, environment_id: str):
        yield FakeStore(self.world)


def book_view(event_id: str, *, bid: str, ask: str, received_ts_ms: int) -> OrderBookView:
    return OrderBookView(
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        bids=(PriceLevel(price=Decimal(bid), quantity=Decimal("10")),),
        asks=(PriceLevel(price=Decimal(ask), quantity=Decimal("10")),),
        depth=5,
        sequence_id=event_id,
        source_event_id=event_id,
        exchange_ts_ms=received_ts_ms - 1,
        received_ts_ms=received_ts_ms,
        quality_status=DataQualityStatus.VALID,
        synchronized=True,
        source_connected=True,
    )


def trade_event(trade_id: str, *, price: str, side: TradeSide, ts_ms: int, received_ms: int):
    return MarketEventEnvelope[Trade](
        event_id=f"okx:trade:{trade_id}",
        event_type="TRADE",
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        source_type=DataSourceType.LIVE,
        transport=TransportType.WEBSOCKET,
        exchange_ts_ms=ts_ms,
        received_ts_ms=received_ms,
        quality_status=DataQualityStatus.VALID,
        payload=Trade(
            trade_id=trade_id,
            price=Decimal(price),
            quantity=Decimal("5"),
            side=side,
        ),
    )


def make_dispatcher(world: World) -> EnvironmentMarketDispatcher:
    return EnvironmentMarketDispatcher(
        transaction=FakeUnitOfWork(world).transaction,
        environment_exists=lambda environment_id: environment_id == "env-1",
        fee_schedule=FEES,
        market_rules=RULES,
        instruments=(INSTRUMENT,),
        now_ms=lambda: world.clock.now_utc_ms(),
        max_book_age_ms=5_000,
        max_trade_age_ms=2_000,
    )


def test_new_environment_receives_current_market_snapshot() -> None:
    world = World()
    dispatcher = make_dispatcher(world)
    dispatcher.apply_order_book_view(book_view("book-1", bid="99", ask="101", received_ts_ms=1_000))
    assert dispatcher.register_environment("env-1") is True
    store = FakeStore(world)
    restored = store.restore_liquidity_optimistic(
        environment_id="env-1", exchange_id=ExchangeId.OKX, instrument_id=INSTRUMENT
    )
    assert restored is not None
    available = restored.available_book()
    assert available.asks[0].price == Decimal("101")
    # Registering an unknown environment must be rejected.
    assert dispatcher.register_environment("env-unknown") is False


def test_trade_through_matching_fills_resting_buy_limit_order() -> None:
    world = World()
    dispatcher = make_dispatcher(world)
    dispatcher.register_environment("env-1")
    order = world.orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("2"),
        limit_price=Decimal("100"),
        fee_schedule=FEES,
    )
    world.clock.set_utc_ms(1_050)
    world.orders.enter_market(order.order_id, market_entry_ts_ms=1_050)
    world.clock.set_utc_ms(1_100)

    dispatcher.apply_trade(
        trade_event("t1", price="99", side=TradeSide.SELL, ts_ms=1_100, received_ms=1_100)
    )

    updated = world.orders.get(order.order_id)
    assert updated.status.value in {"FILLED", "PARTIALLY_FILLED"}
    assert updated.filled_quantity == Decimal("2")
    # TRADE_THROUGH model: maker fills at its own limit price.
    assert updated.average_fill_price == Decimal("100")
    assert world.state_version == 1
    assert world.staged and world.staged[0]["orders"]
    # Duplicate trade events must never double-fill.
    world.clock.set_utc_ms(1_200)
    dispatcher._environments["env-1"]["trade_state"] = None
    world.processed.clear()
    dispatcher.apply_trade(
        trade_event("t1", price="99", side=TradeSide.SELL, ts_ms=1_100, received_ms=1_200)
    )
    assert world.orders.get(order.order_id).filled_quantity == Decimal("2")


def test_trade_engine_ordering_survives_dispatcher_restart() -> None:
    world = World()
    dispatcher = make_dispatcher(world)
    dispatcher.register_environment("env-1")
    dispatcher.apply_trade(
        trade_event("t1", price="99", side=TradeSide.SELL, ts_ms=1_100, received_ms=1_100)
    )
    # A fresh dispatcher (restart) must restore the last ordering key and
    # reject an older trade.
    restarted = make_dispatcher(world)
    restarted.register_environment("env-1")
    restarted.apply_trade(
        trade_event("t0", price="99", side=TradeSide.SELL, ts_ms=1_090, received_ms=1_150)
    )
    assert restarted.stats["trades_ignored"] >= 1


def test_due_market_order_executes_against_current_book() -> None:
    world = World()
    dispatcher = make_dispatcher(world)
    dispatcher.register_environment("env-1")
    dispatcher.apply_order_book_view(book_view("book-1", bid="99", ask="101", received_ts_ms=1_000))
    order = world.orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        market_reference_price=Decimal("101"),
        max_quote_budget=Decimal("102"),
        fee_schedule=FEES,
    )
    scheduler = ExecutionScheduler(world.orders, world.clock)
    scheduler.schedule(
        order.order_id,
        latency=ExecutionLatency(preset=LatencyPreset.IDEAL),
        submission_quote_event_id="book-1",
    )
    store = FakeStore(world)
    store.persist_trading_state(
        environment_id="env-1",
        ledger=world.ledger,
        orders=world.orders,
        executions=(),
        portfolio=PortfolioEngine(),
        scheduler=scheduler,
    )
    world.clock.set_utc_ms(1_500)

    outcome = dispatcher.run_due()

    assert outcome["executed"] == [order.order_id]
    updated = world.orders.get(order.order_id)
    assert updated.status.value == "FILLED"
    assert updated.average_fill_price == Decimal("101")
    assert world.state_version == 1


def test_stale_book_rejects_due_market_order() -> None:
    world = World()
    dispatcher = make_dispatcher(world)
    dispatcher.register_environment("env-1")
    dispatcher.apply_order_book_view(book_view("book-1", bid="99", ask="101", received_ts_ms=1_000))
    order = world.orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        market_reference_price=Decimal("101"),
        max_quote_budget=Decimal("102"),
        fee_schedule=FEES,
    )
    scheduler = ExecutionScheduler(world.orders, world.clock)
    scheduler.schedule(
        order.order_id,
        latency=ExecutionLatency(preset=LatencyPreset.IDEAL),
        submission_quote_event_id="book-1",
    )
    FakeStore(world).persist_trading_state(
        environment_id="env-1",
        ledger=world.ledger,
        orders=world.orders,
        executions=(),
        portfolio=PortfolioEngine(),
        scheduler=scheduler,
    )
    # Book received at 1_000 goes stale once more than max_book_age_ms passes.
    world.clock.set_utc_ms(20_000)

    outcome = dispatcher.run_due()

    assert outcome["rejected"] == [order.order_id]
    updated = world.orders.get(order.order_id)
    assert updated.status.value == "REJECTED"
    assert updated.termination_reason == "MARKET_DATA_UNAVAILABLE"


def test_environments_stay_isolated_from_each_other() -> None:
    world_a = World()
    world_b = World()
    store_a = FakeStore(world_a)

    class DualUnitOfWork:
        @contextlib.contextmanager
        def transaction(self, environment_id: str):
            yield store_a if environment_id == "env-a" else FakeStore(world_b)

    dispatcher = EnvironmentMarketDispatcher(
        transaction=DualUnitOfWork().transaction,
        environment_exists=lambda environment_id: True,
        fee_schedule=FEES,
        market_rules=RULES,
        instruments=(INSTRUMENT,),
        now_ms=lambda: world_a.clock.now_utc_ms(),
    )
    dispatcher.register_environment("env-a")
    dispatcher.register_environment("env-b")
    order = world_a.orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("2"),
        limit_price=Decimal("100"),
        fee_schedule=FEES,
    )
    world_a.clock.set_utc_ms(1_050)
    world_a.orders.enter_market(order.order_id, market_entry_ts_ms=1_050)
    world_a.clock.set_utc_ms(1_100)

    dispatcher.apply_trade(
        trade_event("t1", price="99", side=TradeSide.SELL, ts_ms=1_100, received_ms=1_100)
    )

    assert world_a.orders.get(order.order_id).filled_quantity == Decimal("2")
    assert world_b.executions == ()
    assert world_b.staged == []
    assert world_b.state_version == 0


def test_book_arriving_during_run_due_does_not_reject_the_due_order() -> None:
    """Regression (Task 1.12.10-A audit): run_due executes in a worker thread while the
    feed keeps updating books. A book received after the run's decision time used to
    trip the no-lookahead gate and spuriously reject a valid order as
    MARKET_DATA_UNAVAILABLE. The run must decide against a book snapshot taken at
    its decision time."""
    world = World()
    dispatcher = make_dispatcher(world)
    dispatcher.register_environment("env-1")
    dispatcher.apply_order_book_view(book_view("book-1", bid="99", ask="101", received_ts_ms=1_000))
    order = world.orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        market_reference_price=Decimal("101"),
        max_quote_budget=Decimal("102"),
        fee_schedule=FEES,
    )
    scheduler = ExecutionScheduler(world.orders, world.clock)
    scheduler.schedule(
        order.order_id,
        latency=ExecutionLatency(preset=LatencyPreset.IDEAL),
        submission_quote_event_id="book-1",
    )
    FakeStore(world).persist_trading_state(
        environment_id="env-1",
        ledger=world.ledger,
        orders=world.orders,
        executions=(),
        portfolio=PortfolioEngine(),
        scheduler=scheduler,
    )
    world.clock.set_utc_ms(1_500)
    original = dispatcher._execute_due_order

    def execute_after_new_book(*args, **kwargs):
        # The feed delivers a newer book (received after this run's "now") first.
        dispatcher.apply_order_book_view(
            book_view("book-2", bid="99", ask="101", received_ts_ms=1_520)
        )
        return original(*args, **kwargs)

    dispatcher._execute_due_order = execute_after_new_book

    outcome = dispatcher.run_due()

    assert outcome["rejected"] == []
    assert outcome["executed"] == [order.order_id]
    assert world.orders.get(order.order_id).status.value == "FILLED"


def test_resynchronized_book_generation_resets_liquidity_for_every_registered_environment() -> None:
    """A re-snapshot after an order-book resync must not wedge market matching."""
    from dataclasses import replace

    world = World()
    dispatcher = make_dispatcher(world)
    dispatcher.register_environment("env-1")
    first = book_view("book-1", bid="99", ask="101", received_ts_ms=1_000)
    dispatcher.apply_order_book_view(first)
    for generation, ts in ((2, 1_100), (3, 1_200)):
        resynced = replace(
            book_view(f"book-{generation}", bid="99", ask="101", received_ts_ms=ts),
            synchronization_generation=generation,
        )
        dispatcher.apply_order_book_view(resynced)
    assert dispatcher.stats["dispatch_errors"] == 0
    assert dispatcher.books.latest("okx", INSTRUMENT).synchronization_generation == 3


def test_restart_with_lower_book_generation_resets_persisted_liquidity() -> None:
    """Regression (found by browser E2E): persisted liquidity carries the previous
    process's synchronization generation. A restarted feed counts generations from 1
    again, so every book update used to fail until the counter caught up, wedging
    matching. The first live book per process must replace stale persisted liquidity."""
    from dataclasses import replace

    world = World()
    old_process = make_dispatcher(world)
    old_process.register_environment("env-1")
    old_process.apply_order_book_view(
        replace(
            book_view("old-book", bid="90", ask="95", received_ts_ms=1_000),
            synchronization_generation=7,
        )
    )
    assert old_process.stats["dispatch_errors"] == 0

    restarted = make_dispatcher(world)  # same persisted world, fresh in-memory state
    restarted.register_environment("env-1")
    for name, ts in (("new-book", 2_000), ("new-book-2", 2_100)):
        restarted.apply_order_book_view(book_view(name, bid="99", ask="101", received_ts_ms=ts))

    assert restarted.stats["dispatch_errors"] == 0
    assert restarted.stats["books_synchronized"] == 2
    liquidity = SimulatedLiquidityView("env-1")
    liquidity.restore_state(world.liquidity["env-1"])
    assert liquidity.available_book().asks[0].price == Decimal("101")


def test_run_due_skips_environments_the_precheck_says_have_nothing_due() -> None:
    world = World()
    probes: list[int] = []

    def nothing_due(now_ms: int) -> set[str]:
        probes.append(now_ms)
        return set()

    dispatcher = make_dispatcher(world)
    dispatcher.due_environments = nothing_due
    dispatcher.register_environment("env-1")
    opened: list[str] = []
    real = dispatcher.transaction

    def counting(environment_id: str):
        opened.append(environment_id)
        return real(environment_id)

    dispatcher.transaction = counting
    assert dispatcher.run_due()["executed"] == []
    assert probes and opened == []  # no locking transaction for an idle environment


def test_failed_precheck_falls_back_to_checking_every_environment() -> None:
    world = World()
    dispatcher = make_dispatcher(world)

    def broken(_now_ms: int) -> set[str]:
        raise RuntimeError("probe down")

    dispatcher.due_environments = broken
    dispatcher.register_environment("env-1")
    opened: list[str] = []
    real = dispatcher.transaction
    dispatcher.transaction = lambda environment_id: (
        opened.append(environment_id),
        real(environment_id),
    )[1]
    dispatcher.run_due()
    assert opened == ["env-1"] and dispatcher.stats["dispatch_errors"] == 1
