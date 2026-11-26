"""End-to-end market chain verification against real PostgreSQL.

Chain under test (deterministic market events, no external network):

    canonical market event
      -> dispatcher.apply_order_book_view / apply_trade / run_due
      -> Market State (LatestBookState + per-env liquidity)
      -> Execution Scheduler / TRADE_THROUGH matcher
      -> Execution Unit of Work
      -> PostgreSQL commit
      -> RealtimePublisher.publish_committed
"""

import contextlib
import os
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select

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
from crypto_lab.realtime import EnvironmentMarketDispatcher
from crypto_lab.trading import FeeSchedule, MarketRules

INSTRUMENT = "okx:SPOT:BTC/USDT"
FEES = FeeSchedule(
    schedule_id="chain-test-v1",
    maker_rate=Decimal("0.001"),
    taker_rate=Decimal("0.001"),
)
RULES = MarketRules(
    rules_id="OKX:CHAIN-TEST",
    price_increment=Decimal("0.1"),
    quantity_increment=Decimal("0.00000001"),
    min_quantity=Decimal("0.00001"),
    min_notional=None,
)


class MutableClock:
    def __init__(self) -> None:
        self.now = 1_000

    def set(self, value: int) -> None:
        self.now = value

    def __call__(self) -> int:
        return self.now


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, tuple[object, ...]]] = []

    def publish_committed(self, environment_id: str, events: tuple[object, ...]) -> None:
        self.published.append((environment_id, events))

    @property
    def events(self) -> list[object]:
        return [event for _, events in self.published for event in events]

    def clear(self) -> None:
        self.published.clear()


@pytest.fixture(scope="module")
def database_url() -> str:
    value = os.getenv("CRYPTO_LAB_TEST_DATABASE_URL")
    if not value:
        pytest.skip("CRYPTO_LAB_TEST_DATABASE_URL is not configured")
    return value


class Chain:
    """One deterministic simulation environment wired to the real database."""

    def __init__(self, engine) -> None:
        self.clock = MutableClock()
        self.publisher = RecordingPublisher()
        self.service = ApplicationService(
            engine,
            fee_schedule=FEES,
            now_ms=self.clock,
            realtime_publisher=self.publisher,
        )
        _, environment = self.service.create_environment(
            EnvironmentCreate(name="chain"), "chain-env-key"
        )
        self.environment_id = environment["environment_id"]
        _, account = self.service.create_account(
            self.environment_id,
            AccountCreate(
                exchange_id="okx",
                name="chain",
                initial_asset="USDT",
                initial_amount="10000",
            ),
            "chain-account-key",
        )
        self.account_id = account["account_id"]
        self.dispatcher = EnvironmentMarketDispatcher(
            transaction=self.service.uow.transaction,
            environment_exists=lambda environment_id: True,
            fee_schedule=FEES,
            market_rules=RULES,
            instruments=(INSTRUMENT,),
            now_ms=self.clock,
            max_book_age_ms=5_000,
            max_trade_age_ms=2_000,
        )
        assert self.dispatcher.register_environment(self.environment_id)

    def place_order(self, **overrides) -> dict:
        request = OrderCreate(
            account_id=self.account_id,
            instrument_id=INSTRUMENT,
            side=overrides.get("side", "BUY"),
            order_type=overrides.get("order_type", "MARKET"),
            quantity=overrides.get("quantity", "1"),
            limit_price=overrides.get("limit_price"),
            max_quote_budget=overrides.get("max_quote_budget"),
            latency_preset=overrides.get("latency_preset", "IDEAL"),
            custom_latency_ms=overrides.get("custom_latency_ms"),
        )
        status, response = self.service.create_order(
            self.environment_id, request, f"chain-order-{id(request)}-{self.clock.now}"
        )
        assert status == 201, response
        return response

    def seed_book(self, *, bid: str, ask: str, received_ts_ms: int) -> None:
        view = OrderBookView(
            exchange_id=ExchangeId.OKX,
            instrument_id=INSTRUMENT,
            bids=(PriceLevel(price=Decimal(bid), quantity=Decimal("20")),),
            asks=(PriceLevel(price=Decimal(ask), quantity=Decimal("20")),),
            depth=5,
            sequence_id=f"chain-{received_ts_ms}",
            source_event_id=f"chain-book-{received_ts_ms}",
            exchange_ts_ms=received_ts_ms - 1,
            received_ts_ms=received_ts_ms,
            quality_status=DataQualityStatus.VALID,
            synchronized=True,
            source_connected=True,
        )
        self.dispatcher.apply_order_book_view(view)

    def trade(
        self, trade_id: str, *, price: str, side: TradeSide, ts_ms: int
    ) -> MarketEventEnvelope[Trade]:
        return MarketEventEnvelope[Trade](
            event_id=f"chain:{trade_id}",
            event_type="TRADE",
            exchange_id=ExchangeId.OKX,
            instrument_id=INSTRUMENT,
            source_type=DataSourceType.LIVE,
            transport=TransportType.WEBSOCKET,
            exchange_ts_ms=ts_ms,
            received_ts_ms=ts_ms,
            quality_status=DataQualityStatus.VALID,
            payload=Trade(
                trade_id=trade_id,
                price=Decimal(price),
                quantity=Decimal("5"),
                side=side,
            ),
        )


@pytest.fixture
def chain(database_url: str):
    engine = create_engine(database_url)
    with engine.begin() as connection:
        for table in reversed(schema.metadata.sorted_tables):
            connection.execute(table.delete())
    yield Chain(engine)
    engine.dispose()


def execution_rows(engine, environment_id: str) -> list[dict]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(schema.executions).where(
                schema.executions.c.environment_id == environment_id
            )
        ).mappings()
        return [dict(row) for row in rows]


def balance_rows(engine, account_id: str) -> dict[str, tuple[str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(schema.asset_balances).where(
                schema.asset_balances.c.account_id == account_id
            )
        ).mappings()
        return {row["asset"]: (str(row["available"]), str(row["locked"])) for row in rows}


def order_row(engine, order_id: str) -> dict:
    with engine.connect() as connection:
        row = connection.execute(
            select(schema.paper_orders).where(schema.paper_orders.c.order_id == order_id)
        ).mappings().one()
        return dict(row)


def topic_types(published_events: list[object]) -> list[str]:
    return [event.topic for event in published_events]


def test_market_buy_executes_and_commits_full_chain(chain, database_url) -> None:
    engine = chain.service.engine
    chain.seed_book(bid="99", ask="101", received_ts_ms=chain.clock.now)
    order = chain.place_order(max_quote_budget="105")

    outcome = chain.dispatcher.run_due()

    assert outcome["executed"] == [order["order_id"]]
    stored = order_row(engine, order["order_id"])
    assert stored["status"] == "FILLED"
    assert stored["average_fill_price"] == Decimal("101")
    executions = execution_rows(engine, chain.environment_id)
    assert len(executions) == 1
    assert executions[0]["price"] == Decimal("101")
    balances = balance_rows(engine, chain.account_id)
    assert Decimal(balances["BTC"][0]) == Decimal("1")
    # Buy notional + taker fee leaves the quote balance.
    assert Decimal(balances["USDT"][0]) == Decimal("10000") - Decimal("101") - Decimal("0.101")
    # Committed events carry order, balance, execution and position
    # notifications with the same transaction state version.
    topics = topic_types(chain.publisher.events)
    assert {"orders", "balances", "executions", "positions"} <= set(topics)
    order_events = [event for event in chain.publisher.events if event.topic == "orders"]
    assert order_events[-1].state_version >= 1
    execution_events = [
        event for event in chain.publisher.events if event.topic == "executions"
    ]
    assert len(execution_events) == 1
    assert execution_events[0].payload["price"] == "101"
    position_events = [
        event for event in chain.publisher.events if event.topic == "positions"
    ]
    assert len(position_events) == 1
    assert position_events[0].payload["quantity"] == "1"
    assert position_events[0].payload["instrument_id"] == INSTRUMENT


def test_market_sell_realizes_pnl_and_updates_positions(chain, database_url) -> None:
    engine = chain.service.engine
    chain.seed_book(bid="99", ask="101", received_ts_ms=1_000)
    chain.place_order(side="BUY", max_quote_budget="105")
    assert chain.dispatcher.run_due()["executed"]

    chain.clock.set(2_000)
    chain.seed_book(bid="110", ask="112", received_ts_ms=2_000)
    sell = chain.place_order(side="SELL", quantity="1")
    assert chain.dispatcher.run_due()["executed"]

    sell_stored = order_row(engine, sell["order_id"])
    assert sell_stored["status"] == "FILLED"
    assert sell_stored["average_fill_price"] == Decimal("110")
    executions = execution_rows(engine, chain.environment_id)
    assert len(executions) == 2
    # Realized PnL = sell notional - fee - cost basis(101 + 0.101 buy fee).
    positions = chain.service.positions(chain.environment_id, chain.account_id)
    assert positions == []  # fully closed position is removed from the projection
    balances = balance_rows(engine, chain.account_id)
    expected_quote = (
        Decimal("10000")
        - Decimal("101")
        - Decimal("0.101")  # buy cost and fee
        + Decimal("110")
        - Decimal("0.11")  # sell proceeds minus fee
    )
    assert Decimal(balances["USDT"][0]) == expected_quote


def test_delayed_execution_waits_for_schedule(chain, database_url) -> None:
    engine = chain.service.engine
    chain.seed_book(bid="99", ask="101", received_ts_ms=1_000)
    order = chain.place_order(
        max_quote_budget="105", latency_preset="CUSTOM", custom_latency_ms=500
    )

    # Not yet due: nothing may execute.
    chain.clock.set(1_200)
    assert chain.dispatcher.run_due()["executed"] == []
    stored = order_row(engine, order["order_id"])
    assert stored["status"] == "PENDING_EXECUTION"

    # Due: executes at the then-current book.
    chain.clock.set(1_600)
    chain.seed_book(bid="98", ask="100", received_ts_ms=1_550)
    assert chain.dispatcher.run_due()["executed"] == [order["order_id"]]
    stored = order_row(engine, order["order_id"])
    assert stored["status"] == "FILLED"
    assert stored["scheduled_execution_ts_ms"] == 1_500
    assert stored["executed_ts_ms"] == 1_600
    assert stored["configured_latency_ms"] == 500
    assert stored["actual_simulated_delay_ms"] == 600
    assert stored["scheduler_lag_ms"] == 100


def test_resting_limit_order_fills_on_through_trade(chain, database_url) -> None:
    engine = chain.service.engine
    chain.seed_book(bid="99", ask="101", received_ts_ms=1_000)
    order = chain.place_order(side="BUY", order_type="LIMIT", limit_price="100")
    assert order["status"] in {"PENDING_EXECUTION", "OPEN"}

    # Enter the resting state via the scheduler.
    chain.clock.set(1_050)
    assert chain.dispatcher.run_due()["executed"] == [order["order_id"]]
    resting = order_row(engine, order["order_id"])
    assert resting["status"] == "OPEN"

    # A sell trade through the limit price fills the resting order.
    chain.clock.set(1_200)
    chain.publisher.clear()
    chain.dispatcher.apply_trade(
        chain.trade("t1", price="99", side=TradeSide.SELL, ts_ms=1_200)
    )
    filled = order_row(engine, order["order_id"])
    assert filled["status"] == "FILLED"
    # TRADE_THROUGH model: maker fills at its own limit price.
    assert filled["average_fill_price"] == Decimal("100")
    assert len(execution_rows(engine, chain.environment_id)) == 1
    topics = topic_types(chain.publisher.events)
    assert "orders" in topics and "balances" in topics


def test_duplicate_trade_never_double_settles(chain, database_url) -> None:
    engine = chain.service.engine
    chain.seed_book(bid="99", ask="101", received_ts_ms=1_000)
    chain.place_order(side="BUY", order_type="LIMIT", limit_price="100")
    chain.clock.set(1_050)
    chain.dispatcher.run_due()
    chain.clock.set(1_200)
    trade = chain.trade("dup-1", price="99", side=TradeSide.SELL, ts_ms=1_200)
    chain.dispatcher.apply_trade(trade)
    balances_after_first = balance_rows(engine, chain.account_id)
    executions_after_first = execution_rows(engine, chain.environment_id)

    chain.clock.set(1_300)
    chain.dispatcher.apply_trade(trade)

    assert execution_rows(engine, chain.environment_id) == executions_after_first
    assert balance_rows(engine, chain.account_id) == balances_after_first
    assert chain.dispatcher.stats["trades_ignored"] >= 1


def test_database_rollback_publishes_no_success_events(chain, database_url) -> None:
    engine = chain.service.engine
    chain.seed_book(bid="99", ask="101", received_ts_ms=1_000)
    order = chain.place_order(side="BUY", order_type="LIMIT", limit_price="100")
    chain.clock.set(1_050)
    chain.dispatcher.run_due()
    chain.clock.set(1_200)
    chain.publisher.clear()
    real_transaction = chain.dispatcher.transaction

    @contextlib.contextmanager
    def failing_transaction(environment_id: str):
        with real_transaction(environment_id) as store:
            yield store
            raise RuntimeError("injected failure before commit")

    chain.dispatcher.transaction = failing_transaction
    try:
        # apply_trade isolates environment failures on purpose; the rollback
        # is verified through the persisted state below.
        chain.dispatcher.apply_trade(
            chain.trade("rollback-1", price="99", side=TradeSide.SELL, ts_ms=1_200)
        )
    finally:
        chain.dispatcher.transaction = real_transaction

    # The whole transaction rolled back: no execution, no committed events,
    # and the trade dedup registration is gone so it can be reprocessed.
    assert execution_rows(engine, chain.environment_id) == []
    assert chain.publisher.events == []
    chain.clock.set(1_300)
    chain.dispatcher.apply_trade(
        chain.trade("rollback-1", price="99", side=TradeSide.SELL, ts_ms=1_300)
    )
    filled = order_row(engine, order["order_id"])
    assert filled["status"] == "FILLED"
    assert len(execution_rows(engine, chain.environment_id)) == 1


def test_stale_market_data_blocks_fills(chain, database_url) -> None:
    engine = chain.service.engine
    chain.seed_book(bid="99", ask="101", received_ts_ms=1_000)
    order = chain.place_order(max_quote_budget="105")

    # The book from ts=1_000 is stale beyond max_book_age_ms (5_000) at 10_000.
    chain.clock.set(10_000)
    outcome = chain.dispatcher.run_due()

    assert outcome["rejected"] == [order["order_id"]]
    stored = order_row(engine, order["order_id"])
    assert stored["status"] == "REJECTED"
    assert stored["termination_reason"] == "MARKET_DATA_UNAVAILABLE"
    assert execution_rows(engine, chain.environment_id) == []
    balances = balance_rows(engine, chain.account_id)
    assert Decimal(balances["USDT"][0]) == Decimal("10000")
