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
    ExecutionSimulator,
    FeeSchedule,
    LimitOrderExecutionService,
    LiquidityRole,
    MarketRules,
    OrderService,
    OrderSide,
    OrderStatus,
    OrderType,
    SimulatedLiquidityView,
    create_paper_account,
)

INSTRUMENT = "okx:SPOT:BTC/USDT"
FEES = FeeSchedule(
    schedule_id="MOCK:v1",
    maker_rate=Decimal("0.0005"),
    taker_rate=Decimal("0.001"),
)
RULES = MarketRules(
    rules_id="MOCK:rules:v1",
    price_increment=Decimal("1"),
    quantity_increment=Decimal("1"),
    min_quantity=Decimal("1"),
    min_notional=Decimal("10"),
)


def snapshot(
    *,
    bids: tuple[tuple[str, str], ...] = (("99", "3"), ("98", "3")),
    asks: tuple[tuple[str, str], ...] = (("100", "1"), ("101", "1"), ("102", "3")),
) -> MarketEventEnvelope[OrderBookSnapshot]:
    return MarketEventEnvelope[OrderBookSnapshot](
        event_id="book-1",
        event_type="ORDER_BOOK_SNAPSHOT",
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        source_type=DataSourceType.MOCK,
        transport=TransportType.FILE,
        received_ts_ms=1_000,
        quality_status=DataQualityStatus.VALID,
        payload=OrderBookSnapshot(
            bids=[PriceLevel(price=price, quantity=quantity) for price, quantity in bids],
            asks=[PriceLevel(price=price, quantity=quantity) for price, quantity in asks],
            depth=20,
            sequence_id="1",
            synchronized=True,
        ),
    )


def buy_context(
    *, quantity: str, limit_price: str
) -> tuple[OrderService, OrderBookMarketState, LimitOrderExecutionService, str]:
    orders = OrderService(create_paper_account(ExchangeId.OKX), clock=lambda: 900)
    order = orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal(quantity),
        limit_price=Decimal(limit_price),
        fee_schedule=FEES,
    )
    state = OrderBookMarketState()
    service = LimitOrderExecutionService(
        state,
        ExecutionSimulator(orders),
        SimulatedLiquidityView("run-1"),
    )
    return orders, state, service, order.order_id


def enter(
    service: LimitOrderExecutionService,
    order_id: str,
):
    return service.enter_limit_order(
        order_id,
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        market_entry_ts_ms=1_000,
        max_book_age_ms=2_000,
        fee_schedule=FEES,
        market_rules=RULES,
        consumption_id="entry-1",
    )


def test_ex_009_marketable_limit_buy_uses_book_prices_and_taker_fee() -> None:
    orders, state, service, order_id = buy_context(quantity="2", limit_price="101")
    state.apply_snapshot(snapshot())

    result = enter(service, order_id)

    assert [execution.price for execution in result.executions] == [
        Decimal("100"),
        Decimal("101"),
    ]
    assert all(execution.liquidity_role is LiquidityRole.TAKER for execution in result.executions)
    assert sum((execution.fee_amount for execution in result.executions), Decimal(0)) == Decimal(
        "0.201"
    )
    assert orders.get(order_id).status is OrderStatus.FILLED
    assert not result.resting


def test_marketable_limit_sell_never_executes_below_limit() -> None:
    ledger = create_paper_account(
        ExchangeId.OKX,
        initial_asset="BTC",
        initial_amount=Decimal("3"),
    )
    orders = OrderService(ledger, clock=lambda: 900)
    order = orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("3"),
        limit_price=Decimal("99"),
        fee_schedule=FEES,
    )
    state = OrderBookMarketState()
    state.apply_snapshot(
        snapshot(
            bids=(("100", "1"), ("99", "1"), ("98", "3")),
            asks=(("101", "1"), ("102", "1"), ("103", "3")),
        )
    )
    service = LimitOrderExecutionService(
        state,
        ExecutionSimulator(orders),
        SimulatedLiquidityView("run-1"),
    )

    result = enter(service, order.order_id)

    assert [execution.price for execution in result.executions] == [
        Decimal("100"),
        Decimal("99"),
    ]
    assert orders.get(order.order_id).status is OrderStatus.PARTIALLY_FILLED
    assert result.resting


def test_immediate_partial_fill_enters_gtc_and_keeps_remaining_funds_locked() -> None:
    orders, state, service, order_id = buy_context(quantity="3", limit_price="101")
    state.apply_snapshot(snapshot())

    result = enter(service, order_id)

    order = orders.get(order_id)
    assert order.status is OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity == Decimal("2")
    assert order.market_entry_ts_ms == 1_000
    assert result.resting
    assert orders.ledger.balance("USDT").locked == Decimal("102.102")

    orders.cancel(order_id)
    assert orders.ledger.balance("USDT").locked == 0


def test_non_marketable_limit_order_enters_resting_without_fill() -> None:
    orders, state, service, order_id = buy_context(quantity="2", limit_price="99")
    state.apply_snapshot(snapshot())

    result = enter(service, order_id)

    assert result.executions == ()
    assert result.plan.filled_quantity == 0
    assert result.resting
    assert orders.get(order_id).status is OrderStatus.OPEN
    assert orders.get(order_id).market_entry_ts_ms == 1_000
