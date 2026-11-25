from decimal import Decimal

import pytest

from crypto_lab.market_data import InvalidOrderBookStateError, OrderBookMarketState
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
    MarketRules,
    OrderBookExecutionService,
    OrderService,
    OrderSide,
    OrderStatus,
    OrderType,
    SimulatedLiquidityView,
    create_paper_account,
)

INSTRUMENT = "okx:SPOT:BTC/USDT"
RULES = MarketRules(
    rules_id="MOCK:BTC-USDT:v1",
    price_increment=Decimal("1"),
    quantity_increment=Decimal("1"),
    min_quantity=Decimal("1"),
    min_notional=Decimal("10"),
)


def snapshot(
    *,
    quality: DataQualityStatus = DataQualityStatus.VALID,
    synchronized: bool = True,
    received_ts_ms: int = 1_000,
) -> MarketEventEnvelope[OrderBookSnapshot]:
    return MarketEventEnvelope[OrderBookSnapshot](
        event_id="book-1",
        event_type="ORDER_BOOK_SNAPSHOT",
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        source_type=DataSourceType.MOCK,
        transport=TransportType.FILE,
        received_ts_ms=received_ts_ms,
        quality_status=quality,
        payload=OrderBookSnapshot(
            bids=[PriceLevel(price="99", quantity="5")],
            asks=[
                PriceLevel(price="100", quantity="1"),
                PriceLevel(price="101", quantity="1"),
            ],
            depth=20,
            sequence_id="1",
            synchronized=synchronized,
        ),
    )


def context() -> tuple[OrderService, OrderBookMarketState, OrderBookExecutionService, str]:
    orders = OrderService(create_paper_account(ExchangeId.OKX))
    order = orders.place(
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("2"),
        market_reference_price=Decimal("101"),
        estimated_buy_fee_rate=Decimal("0.001"),
    )
    state = OrderBookMarketState()
    service = OrderBookExecutionService(
        state,
        ExecutionSimulator(orders),
        SimulatedLiquidityView("run-1"),
    )
    return orders, state, service, order.order_id


def test_service_executes_only_from_valid_market_state() -> None:
    orders, state, service, order_id = context()
    state.apply_snapshot(snapshot())

    result = service.execute_market_order(
        order_id,
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        decision_ts_ms=1_000,
        max_book_age_ms=2_000,
        fee_rate=Decimal("0.001"),
        market_rules=RULES,
        consumption_id="match-1",
    )

    assert len(result.executions) == 2
    assert result.plan.total_notional == Decimal("201")
    assert orders.get(order_id).status is OrderStatus.FILLED


@pytest.mark.parametrize(
    ("event", "decision_ts_ms", "message"),
    [
        (snapshot(quality=DataQualityStatus.INVALID), 1_000, "quality"),
        (snapshot(synchronized=False), 1_000, "not synchronized"),
        (snapshot(), 3_001, "stale"),
        (snapshot(received_ts_ms=2_000), 1_000, "after decision"),
    ],
)
def test_invalid_market_state_cannot_mutate_order_or_ledger(
    event: MarketEventEnvelope[OrderBookSnapshot],
    decision_ts_ms: int,
    message: str,
) -> None:
    orders, state, service, order_id = context()
    state.apply_snapshot(event)
    before_entries = orders.ledger.entries

    with pytest.raises(InvalidOrderBookStateError, match=message):
        service.execute_market_order(
            order_id,
            exchange_id=ExchangeId.OKX,
            instrument_id=INSTRUMENT,
            decision_ts_ms=decision_ts_ms,
            max_book_age_ms=2_000,
            fee_rate=Decimal("0.001"),
            market_rules=RULES,
            consumption_id="match-1",
        )

    assert orders.get(order_id).status is OrderStatus.OPEN
    assert orders.ledger.entries == before_entries


def test_disconnected_market_state_cannot_execute() -> None:
    orders, state, service, order_id = context()
    state.apply_snapshot(snapshot())
    state.mark_disconnected(ExchangeId.OKX, INSTRUMENT)

    with pytest.raises(InvalidOrderBookStateError, match="disconnected"):
        service.execute_market_order(
            order_id,
            exchange_id=ExchangeId.OKX,
            instrument_id=INSTRUMENT,
            decision_ts_ms=1_000,
            max_book_age_ms=2_000,
            fee_rate=Decimal("0.001"),
            market_rules=RULES,
            consumption_id="match-1",
        )

    assert orders.get(order_id).status is OrderStatus.OPEN
