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
    DeterministicIdGenerator,
    ExecutionLatency,
    ExecutionScheduler,
    ExecutionSimulator,
    FeeSchedule,
    InMemoryUnitOfWork,
    LatencyPreset,
    LimitOrderExecutionService,
    ManualClock,
    MarketRules,
    OrderBookExecutionService,
    OrderService,
    OrderSide,
    OrderType,
    PortfolioEngine,
    ScheduledOrderExecutor,
    SerialEventProcessor,
    SimulatedLiquidityView,
    SimulationEventKind,
    create_paper_account,
)

INSTRUMENT = "okx:SPOT:BTC/USDT"


def replay_experiment() -> tuple[object, ...]:
    ids = DeterministicIdGenerator("replay-environment")
    clock = ManualClock(900)
    ledger = create_paper_account(
        ExchangeId.OKX,
        id_generator=ids,
        clock=clock,
    )
    orders = OrderService(ledger, clock=clock)
    portfolio = PortfolioEngine()
    simulator = ExecutionSimulator(orders, portfolio=portfolio)
    state = OrderBookMarketState()
    liquidity = SimulatedLiquidityView("replay-environment")
    scheduler = ExecutionScheduler(orders, clock)
    uow = InMemoryUnitOfWork(
        (clock, ids, ledger, orders, simulator, portfolio, state, liquidity, scheduler)
    )
    market_execution = OrderBookExecutionService(state, simulator, liquidity)
    limit_execution = LimitOrderExecutionService(state, simulator, liquidity)
    executor = ScheduledOrderExecutor(
        orders=orders,
        market_state=state,
        market_execution=market_execution,
        limit_execution=limit_execution,
        unit_of_work=uow,
    )
    uow.add_participant(executor)
    events = SerialEventProcessor("replay-environment", uow, clock=clock)
    order_ref: dict[str, str] = {}
    fees = FeeSchedule(
        schedule_id="REPLAY:FEES",
        maker_rate=Decimal("0.001"),
        taker_rate=Decimal("0.01"),
    )
    rules = MarketRules(
        rules_id="REPLAY:RULES",
        price_increment=Decimal("1"),
        quantity_increment=Decimal("1"),
        min_quantity=Decimal("1"),
        min_notional=Decimal("10"),
    )

    def submit_order() -> str:
        order = orders.place(
            instrument_id=INSTRUMENT,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            market_reference_price=Decimal("100"),
            max_quote_budget=Decimal("101"),
            fee_schedule=fees,
        )
        order_ref["id"] = order.order_id
        scheduler.schedule(
            order.order_id,
            latency=ExecutionLatency(preset=LatencyPreset.NORMAL),
            submission_quote_event_id="submission-book",
        )
        executor.register(
            order.order_id,
            exchange_id=ExchangeId.OKX,
            max_book_age_ms=500,
            fee_schedule=fees,
            market_rules=rules,
            consumption_id="scheduled-fill-1",
        )
        return order.order_id

    snapshot = MarketEventEnvelope[OrderBookSnapshot](
        event_id="execution-book",
        event_type="ORDER_BOOK_SNAPSHOT",
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        source_type=DataSourceType.MOCK,
        transport=TransportType.FILE,
        exchange_ts_ms=1_099,
        received_ts_ms=1_100,
        quality_status=DataQualityStatus.VALID,
        payload=OrderBookSnapshot(
            bids=(PriceLevel(price="99", quantity="2"),),
            asks=(PriceLevel(price="100", quantity="2"),),
            depth=10,
            sequence_id="1",
            synchronized=True,
        ),
    )
    events.enqueue(
        event_id="submit-1",
        timestamp_ms=1_000,
        kind=SimulationEventKind.ORDER_SUBMISSION,
        handler=submit_order,
    )
    events.enqueue(
        event_id="execute-1",
        timestamp_ms=1_100,
        kind=SimulationEventKind.SCHEDULED_EXECUTION,
        handler=lambda: scheduler.run_due(executor),
    )
    events.enqueue(
        event_id="book-1",
        timestamp_ms=1_100,
        kind=SimulationEventKind.MARKET_DATA,
        handler=lambda: state.apply_snapshot(snapshot),
    )
    results = events.process_all()
    order = orders.get(order_ref["id"])

    return (
        order.model_dump(mode="json"),
        tuple(item.model_dump(mode="json") for item in simulator.executions()),
        tuple(item.model_dump(mode="json") for item in ledger.entries),
        tuple(item.model_dump(mode="json") for item in ledger.balances()),
        tuple(item.model_dump(mode="json") for item in portfolio.positions()),
        liquidity.available_book(),
        tuple((result.event.event_id, result.status) for result in results),
        executor.outcome(order.order_id).model_dump(mode="json"),
    )


def test_complete_engine_experiment_replays_identically() -> None:
    assert replay_experiment() == replay_experiment()
