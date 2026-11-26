"""Application-lifecycle restart recovery against real PostgreSQL.

Time is fully controlled (MutableClock); no exchange network is used. Each
"restart" builds a fresh app over the same database, exactly like a process
restart: the in-memory dispatcher, books and scheduler state are lost and only
PostgreSQL survives.
"""

from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from crypto_lab.api.app import create_app
from crypto_lab.api.market_feed import MarketFeedSettings
from crypto_lab.api.schemas import AccountCreate, EnvironmentCreate, OrderCreate
from crypto_lab.api.service import ApplicationService
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
from crypto_lab.persistence import schema
from crypto_lab.realtime.dispatch import EXECUTION_EXPIRED_ON_RESTART
from crypto_lab.trading import FeeSchedule

INSTRUMENT = "okx:SPOT:BTC/USDT"
FEES = FeeSchedule(
    schedule_id="phase1-default-v1",
    maker_rate=Decimal("0.001"),
    taker_rate=Decimal("0.001"),
)


class IdleFeed:
    """Stands in for the exchange feed: no network, runs until stopped."""

    def __init__(self) -> None:
        self._stop = False

    async def run(self) -> None:
        while not self._stop:
            await asyncio.sleep(0.01)

    async def stop(self) -> None:
        self._stop = True


class World:
    """Pre-restart state written through the real service (the 'old process')."""

    def __init__(self, engine, clock) -> None:
        self.engine = engine
        self.clock = clock
        self.service = ApplicationService(engine, fee_schedule=FEES, now_ms=clock)

    def environment(self, name: str) -> tuple[str, str]:
        _, env = self.service.create_environment(EnvironmentCreate(name=name), f"env-{name}")
        _, acc = self.service.create_account(
            env["environment_id"],
            AccountCreate(
                exchange_id="okx", name=name, initial_asset="USDT", initial_amount="10000"
            ),
            f"acc-{name}",
        )
        return env["environment_id"], acc["account_id"]

    def old_dispatcher(self, env: str):
        """The pre-restart process's dispatcher, registered for ``env``."""
        from crypto_lab.realtime import EnvironmentMarketDispatcher
        from crypto_lab.trading import MarketRules

        dispatcher = EnvironmentMarketDispatcher(
            transaction=self.service.uow.transaction,
            environment_exists=lambda _e: True,
            fee_schedule=FEES,
            market_rules=MarketRules(
                rules_id="T",
                price_increment=Decimal("0.1"),
                quantity_increment=Decimal("0.00000001"),
                min_quantity=Decimal("0.00001"),
                min_notional=None,
            ),
            instruments=(INSTRUMENT,),
            now_ms=self.clock,
        )
        dispatcher.register_environment(env)
        return dispatcher

    def seed_liquidity(self, env: str) -> None:
        """Persist a valid book for ``env`` so market orders can be accepted."""
        self.old_dispatcher(env).apply_order_book_view(book(self.clock.now))

    def order(self, env: str, acc: str, key: str, **kw) -> dict:
        request = OrderCreate(
            account_id=acc,
            instrument_id=INSTRUMENT,
            side=kw.get("side", "BUY"),
            order_type=kw.get("order_type", "MARKET"),
            quantity=kw.get("quantity", "1"),
            limit_price=kw.get("limit_price"),
            max_quote_budget=kw.get("max_quote_budget"),
            latency_preset=kw.get("latency_preset", "CUSTOM"),
            custom_latency_ms=kw.get("custom_latency_ms", 500),
        )
        status, response = self.service.create_order(env, request, key)
        assert status == 201, response
        return response


def start_app(engine, clock, *, before_start=None):
    app = create_app(
        engine=engine,
        market_feed=IdleFeed(),
        market_feed_settings=MarketFeedSettings(enabled=True),
        now_ms=clock,
    )
    if before_start is not None:
        before_start(app)
    return app


def book(received_ts_ms: int, bid="99", ask="101") -> OrderBookView:
    return OrderBookView(
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        bids=(PriceLevel(price=Decimal(bid), quantity=Decimal("20")),),
        asks=(PriceLevel(price=Decimal(ask), quantity=Decimal("20")),),
        depth=5,
        sequence_id=f"b-{received_ts_ms}",
        source_event_id=f"book-{received_ts_ms}",
        exchange_ts_ms=received_ts_ms - 1,
        received_ts_ms=received_ts_ms,
        quality_status=DataQualityStatus.VALID,
        synchronized=True,
        source_connected=True,
    )


def trade(trade_id: str, price: str, qty: str, ts_ms: int) -> MarketEventEnvelope[Trade]:
    return MarketEventEnvelope[Trade](
        event_id=f"t:{trade_id}",
        event_type="TRADE",
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        source_type=DataSourceType.LIVE,
        transport=TransportType.WEBSOCKET,
        exchange_ts_ms=ts_ms,
        received_ts_ms=ts_ms,
        quality_status=DataQualityStatus.VALID,
        payload=Trade(
            trade_id=trade_id, price=Decimal(price), quantity=Decimal(qty), side=TradeSide.SELL
        ),
    )


def order_row(engine, order_id: str) -> dict:
    with engine.connect() as connection:
        return dict(
            connection.execute(
                select(schema.paper_orders).where(schema.paper_orders.c.order_id == order_id)
            )
            .mappings()
            .one()
        )


def balances(engine, account_id: str) -> dict[str, tuple[Decimal, Decimal]]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(schema.asset_balances).where(schema.asset_balances.c.account_id == account_id)
        ).mappings()
        return {row["asset"]: (row["available"], row["locked"]) for row in rows}


def count(engine, table) -> int:
    with engine.connect() as connection:
        return connection.execute(select(func.count()).select_from(table)).scalar_one()


def schedule_rows(engine, order_id: str) -> list[dict]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(schema.scheduled_executions).where(
                schema.scheduled_executions.c.order_id == order_id
            )
        ).mappings()
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------


def test_restart_reregisters_environments(engine, clock) -> None:
    world = World(engine, clock)
    env_a, _ = world.environment("a")
    env_b, _ = world.environment("b")
    clock.now = 50_000
    app = start_app(engine, clock)
    with TestClient(app) as client:
        assert sorted(app.state.market_dispatcher.environments()) == sorted([env_a, env_b])
        status = client.get("/health/recovery").json()
        assert status["failed"] == {}
        assert sorted(status["recovered"]) == sorted([env_a, env_b])


def test_overdue_pending_order_is_rejected_even_when_a_valid_book_exists(engine, clock) -> None:
    world = World(engine, clock)
    env, acc = world.environment("overdue")
    world.seed_liquidity(env)
    order = world.order(env, acc, "o1", max_quote_budget="105", custom_latency_ms=500)
    assert balances(engine, acc)["USDT"] == (Decimal("9895"), Decimal("105"))
    clock.now = 90_000  # long downtime; scheduled time (1_500) is far in the past

    app = start_app(
        engine,
        clock,
        # A valid, fresh executable book is already known before recovery runs.
        before_start=lambda a: a.state.market_dispatcher.apply_order_book_view(book(89_999)),
    )
    with TestClient(app):
        dispatcher = app.state.market_dispatcher
        assert dispatcher.run_due() == {"executed": [], "rejected": [], "executed_ts_ms": 90_000}

    stored = order_row(engine, order["order_id"])
    assert stored["status"] == "REJECTED"
    assert stored["termination_reason"] == EXECUTION_EXPIRED_ON_RESTART
    assert stored["filled_quantity"] == 0
    assert stored["executed_ts_ms"] is None  # never executed: no fabricated timing
    assert balances(engine, acc)["USDT"] == (Decimal("10000"), Decimal("0"))
    assert count(engine, schema.executions) == 0
    assert count(engine, schema.liquidity_consumptions) == 0
    assert schedule_rows(engine, order["order_id"]) == []


def test_not_yet_due_order_keeps_its_schedule_and_executes_when_due(engine, clock) -> None:
    world = World(engine, clock)
    env, acc = world.environment("future")
    world.seed_liquidity(env)
    order = world.order(env, acc, "o1", max_quote_budget="105", custom_latency_ms=60_000)
    scheduled = order_row(engine, order["order_id"])["scheduled_execution_ts_ms"]
    assert scheduled == 61_000
    clock.now = 30_000

    app = start_app(engine, clock)
    with TestClient(app):
        dispatcher = app.state.market_dispatcher
        stored = order_row(engine, order["order_id"])
        assert stored["status"] == "PENDING_EXECUTION"
        assert stored["scheduled_execution_ts_ms"] == scheduled
        assert stored["configured_latency_ms"] == 60_000
        assert balances(engine, acc)["USDT"] == (Decimal("9895"), Decimal("105"))
        assert len(schedule_rows(engine, order["order_id"])) == 1

        clock.now = 61_000
        dispatcher.apply_order_book_view(book(61_000))
        assert dispatcher.run_due()["executed"] == [order["order_id"]]
    assert order_row(engine, order["order_id"])["status"] == "FILLED"
    assert count(engine, schema.executions) == 1


def _open_resting_limit(world: World, env: str, acc: str, quantity: str) -> dict:
    """Old process: place a GTC limit buy and let it enter the market (OPEN)."""
    old = world.old_dispatcher(env)
    old.apply_order_book_view(book(world.clock.now))
    order = world.order(
        env,
        acc,
        "limit-1",
        order_type="LIMIT",
        side="BUY",
        quantity=quantity,
        limit_price="100",
        latency_preset="IDEAL",
        custom_latency_ms=None,
    )
    world.clock.now += 10
    old.run_due()
    assert order_row(world.engine, order["order_id"])["status"] == "OPEN"
    return order


def test_resting_gtc_limit_order_keeps_matching_after_restart(engine, clock) -> None:
    world = World(engine, clock)
    env, acc = world.environment("gtc")
    order = _open_resting_limit(world, env, acc, "1")
    locked_before = balances(engine, acc)["USDT"][1]
    clock.now = 80_000  # long downtime; no fill may be invented for it

    app = start_app(engine, clock)
    with TestClient(app):
        dispatcher = app.state.market_dispatcher
        assert order_row(engine, order["order_id"])["status"] == "OPEN"
        assert balances(engine, acc)["USDT"][1] == locked_before
        assert count(engine, schema.executions) == 0
        # Only a new market event may fill it.
        dispatcher.apply_trade(trade("post-restart", "99", "5", 80_000))
    stored = order_row(engine, order["order_id"])
    assert stored["status"] == "FILLED"
    assert stored["average_fill_price"] == Decimal("100")
    assert count(engine, schema.executions) == 1


def test_partially_filled_limit_order_is_restored_and_completes(engine, clock) -> None:
    world = World(engine, clock)
    env, acc = world.environment("partial")
    order = _open_resting_limit(world, env, acc, "8")

    # Old process also processes a partial through-trade (5 of 8) before shutdown.
    old = world.old_dispatcher(env)
    world.clock.now += 100
    old.apply_trade(trade("pre-1", "99", "5", world.clock.now))
    partial = order_row(engine, order["order_id"])
    assert partial["status"] == "PARTIALLY_FILLED"
    assert partial["filled_quantity"] == Decimal("5")
    executions_before = count(engine, schema.executions)
    ledger_before = count(engine, schema.ledger_entries)
    locked_before = balances(engine, acc)["USDT"][1]

    clock.now = 70_000
    app = start_app(engine, clock)
    with TestClient(app):
        dispatcher = app.state.market_dispatcher
        restored = order_row(engine, order["order_id"])
        assert restored["status"] == "PARTIALLY_FILLED"
        assert restored["filled_quantity"] == Decimal("5")
        assert balances(engine, acc)["USDT"][1] == locked_before  # remaining reservation kept
        assert count(engine, schema.executions) == executions_before
        assert count(engine, schema.ledger_entries) == ledger_before
        # The pre-restart trade must never be settled twice.
        dispatcher.apply_trade(trade("pre-1", "99", "5", 70_000))
        assert count(engine, schema.executions) == executions_before
        clock.now = 70_001  # a trade stamped after "now" is rejected as future-dated
        dispatcher.apply_trade(trade("post-1", "99", "5", 70_001))
    assert order_row(engine, order["order_id"])["status"] == "FILLED"
    assert count(engine, schema.executions) == executions_before + 1


def test_repeated_restarts_are_idempotent(engine, clock) -> None:
    world = World(engine, clock)
    env, acc = world.environment("idem")
    world.seed_liquidity(env)
    world.order(env, acc, "o-over", max_quote_budget="105", custom_latency_ms=500)
    clock.now = 40_000

    with TestClient(start_app(engine, clock)):
        pass
    snapshot = (
        count(engine, schema.ledger_entries),
        count(engine, schema.executions),
        count(engine, schema.simulation_events),
        balances(engine, acc),
    )
    with engine.connect() as connection:
        version = connection.execute(
            select(schema.simulation_environments.c.state_version).where(
                schema.simulation_environments.c.environment_id == env
            )
        ).scalar_one()

    for _ in range(2):
        clock.now += 5_000
        with TestClient(start_app(engine, clock)):
            pass

    assert snapshot == (
        count(engine, schema.ledger_entries),
        count(engine, schema.executions),
        count(engine, schema.simulation_events),
        balances(engine, acc),
    )
    with engine.connect() as connection:
        assert version == connection.execute(
            select(schema.simulation_environments.c.state_version).where(
                schema.simulation_environments.c.environment_id == env
            )
        ).scalar_one()


def _failing_for(environment_id: str):
    def install(app) -> None:
        dispatcher = app.state.market_dispatcher
        real = dispatcher.transaction

        @contextlib.contextmanager
        def transaction(env: str):
            with real(env) as store:
                if env == environment_id:
                    raise RuntimeError("injected recovery failure")
                yield store

        dispatcher.transaction = transaction
        app.state.restore_real_transaction = lambda: setattr(dispatcher, "transaction", real)

    return install


def test_one_failing_environment_is_isolated_and_reported(engine, clock) -> None:
    world = World(engine, clock)
    bad_env, bad_acc = world.environment("bad")
    good_env, good_acc = world.environment("good")
    world.seed_liquidity(bad_env)
    world.seed_liquidity(good_env)
    bad_order = world.order(bad_env, bad_acc, "ob", max_quote_budget="105")
    good_order = world.order(good_env, good_acc, "og", max_quote_budget="105")
    clock.now = 30_000

    app = start_app(engine, clock, before_start=_failing_for(bad_env))
    with TestClient(app) as client:
        status = client.get("/health/recovery").json()
        assert list(status["failed"]) == [bad_env]
        assert "injected recovery failure" in status["failed"][bad_env]
        assert status["recovered"] == [good_env]
        dispatcher = app.state.market_dispatcher
        # The healthy environment was recovered; the failed one is untouched
        # and never matched while unrecovered.
        assert order_row(engine, good_order["order_id"])["status"] == "REJECTED"
        assert order_row(engine, bad_order["order_id"])["status"] == "PENDING_EXECUTION"
        dispatcher.apply_order_book_view(book(29_999))
        dispatcher.run_due()
        assert order_row(engine, bad_order["order_id"])["status"] == "PENDING_EXECUTION"

        # Retry after the fault clears recovers it with the same rules.
        app.state.restore_real_transaction()
        results = dispatcher.restore_environments([bad_env], 31_000)
        assert [r.status for r in results] == ["RECOVERED"]
        assert dispatcher.recovery_status()["failed"] == {}
    stored = order_row(engine, bad_order["order_id"])
    assert stored["status"] == "REJECTED"
    assert stored["termination_reason"] == EXECUTION_EXPIRED_ON_RESTART
    assert balances(engine, bad_acc)["USDT"] == (Decimal("10000"), Decimal("0"))


def test_database_failure_during_recovery_rolls_back_atomically(engine, clock) -> None:
    world = World(engine, clock)
    env, acc = world.environment("atomic")
    world.seed_liquidity(env)
    order = world.order(env, acc, "o1", max_quote_budget="105")
    before_entries = count(engine, schema.ledger_entries)
    clock.now = 30_000

    app = start_app(engine, clock, before_start=_failing_for(env))
    with TestClient(app) as client:
        assert env in client.get("/health/recovery").json()["failed"]
    # Failure raised after the recovery work but before commit: nothing persisted.
    assert order_row(engine, order["order_id"])["status"] == "PENDING_EXECUTION"
    assert balances(engine, acc)["USDT"] == (Decimal("9895"), Decimal("105"))
    assert count(engine, schema.ledger_entries) == before_entries
    assert len(schedule_rows(engine, order["order_id"])) == 1
