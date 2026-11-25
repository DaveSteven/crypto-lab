from dataclasses import replace
from decimal import Decimal

import pytest

from crypto_lab.market_data import OrderBookView
from crypto_lab.models import DataQualityStatus, ExchangeId, PriceLevel
from crypto_lab.trading import (
    LiquidityError,
    OrderSide,
    SimulatedLiquidityView,
    match_market_order,
)


def book(
    event_id: str,
    *,
    bid_quantity: str = "5",
    ask_quantity: str = "5",
    generation: int = 1,
) -> OrderBookView:
    return OrderBookView(
        exchange_id=ExchangeId.OKX,
        instrument_id="okx:SPOT:BTC/USDT",
        bids=(PriceLevel(price="99", quantity=bid_quantity),),
        asks=(PriceLevel(price="100", quantity=ask_quantity),),
        depth=20,
        sequence_id=event_id,
        source_event_id=event_id,
        exchange_ts_ms=1_000,
        received_ts_ms=1_000,
        quality_status=DataQualityStatus.VALID,
        synchronized=True,
        source_connected=True,
        synchronization_generation=generation,
    )


def buy_plan(view: SimulatedLiquidityView, quantity: str):
    return match_market_order(
        view.available_book(),
        side=OrderSide.BUY,
        quantity=Decimal(quantity),
        submission_reference_price=Decimal("100"),
    )


def test_ex_008_consumed_liquidity_is_not_reused() -> None:
    liquidity = SimulatedLiquidityView("experiment-1")
    liquidity.synchronize(book("book-1"))
    first = buy_plan(liquidity, "3")
    liquidity.consume(first, consumption_id="fill-1")

    second = buy_plan(liquidity, "3")
    assert second.filled_quantity == Decimal("2")
    liquidity.consume(second, consumption_id="fill-2")
    assert liquidity.available_book().asks == ()


def test_duplicate_or_excess_consumption_is_atomic() -> None:
    liquidity = SimulatedLiquidityView("experiment-1")
    liquidity.synchronize(book("book-1"))
    plan = buy_plan(liquidity, "3")
    liquidity.consume(plan, consumption_id="fill-1")
    before = liquidity.available_book()

    with pytest.raises(LiquidityError, match="duplicate"):
        liquidity.consume(plan, consumption_id="fill-1")
    with pytest.raises(LiquidityError, match="exceeds"):
        liquidity.consume(plan, consumption_id="fill-2")
    assert liquidity.available_book() == before


def test_continuous_market_update_only_adds_observed_increment() -> None:
    liquidity = SimulatedLiquidityView("experiment-1")
    liquidity.synchronize(book("book-1", ask_quantity="5"))
    liquidity.consume(buy_plan(liquidity, "3"), consumption_id="fill-1")

    liquidity.synchronize(book("book-2", ask_quantity="6"))
    assert liquidity.available_book().asks[0].quantity == Decimal("3")

    liquidity.synchronize(book("book-3", ask_quantity="4"))
    assert liquidity.available_book().asks[0].quantity == Decimal("1")


def test_new_generation_requires_explicit_reset() -> None:
    liquidity = SimulatedLiquidityView("experiment-1")
    liquidity.synchronize(book("book-1"))
    liquidity.consume(buy_plan(liquidity, "3"), consumption_id="fill-1")
    resynchronized = book("book-2", generation=2)

    with pytest.raises(LiquidityError, match="explicit liquidity reset"):
        liquidity.synchronize(resynchronized)
    assert liquidity.available_book().asks[0].quantity == Decimal("2")

    reset = liquidity.reset_for_resynchronized_book(resynchronized)
    assert reset.asks[0].quantity == Decimal("5")


def test_environments_have_independent_liquidity_views() -> None:
    first = SimulatedLiquidityView("experiment-1")
    second = SimulatedLiquidityView("experiment-2")
    market = book("book-1")
    first.synchronize(market)
    second.synchronize(market)
    first.consume(buy_plan(first, "3"), consumption_id="fill-1")

    assert first.available_book().asks[0].quantity == Decimal("2")
    assert second.available_book().asks[0].quantity == Decimal("5")


def test_plan_from_previous_market_event_cannot_consume_new_view() -> None:
    liquidity = SimulatedLiquidityView("experiment-1")
    liquidity.synchronize(book("book-1"))
    old_plan = buy_plan(liquidity, "1")
    liquidity.synchronize(book("book-2", ask_quantity="6"))

    with pytest.raises(LiquidityError, match="different order-book event"):
        liquidity.consume(old_plan, consumption_id="fill-1")


def test_market_identity_cannot_change() -> None:
    liquidity = SimulatedLiquidityView("experiment-1")
    liquidity.synchronize(book("book-1"))
    other = replace(book("book-2"), instrument_id="okx:SPOT:ETH/USDT")

    with pytest.raises(LiquidityError, match="market identity"):
        liquidity.synchronize(other)
