from decimal import Decimal

import pytest

from crypto_lab.market_data import OrderBookView
from crypto_lab.models import DataQualityStatus, ExchangeId, PriceLevel
from crypto_lab.trading import MatchStatus, OrderSide, match_market_order


def book(
    *,
    bids: tuple[tuple[str, str], ...] = (("99", "10"),),
    asks: tuple[tuple[str, str], ...] = (("100", "10"),),
) -> OrderBookView:
    return OrderBookView(
        exchange_id=ExchangeId.OKX,
        instrument_id="okx:SPOT:BTC/USDT",
        bids=tuple(PriceLevel(price=price, quantity=quantity) for price, quantity in bids),
        asks=tuple(PriceLevel(price=price, quantity=quantity) for price, quantity in asks),
        depth=20,
        sequence_id="10",
        source_event_id="book-10",
        exchange_ts_ms=900,
        received_ts_ms=1_000,
        quality_status=DataQualityStatus.VALID,
        synchronized=True,
        source_connected=True,
    )


def test_ex_001_single_level_market_buy() -> None:
    plan = match_market_order(
        book(),
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        submission_reference_price=Decimal("100"),
    )

    assert plan.status is MatchStatus.FILLED
    assert plan.filled_quantity == Decimal("2")
    assert plan.total_notional == Decimal("200")
    assert plan.vwap == Decimal("100")
    assert len(plan.fills) == 1


def test_ex_002_multi_level_market_buy_and_slippage() -> None:
    plan = match_market_order(
        book(asks=(("100", "1"), ("101", "2"), ("102", "3"))),
        side=OrderSide.BUY,
        quantity=Decimal("3"),
        submission_reference_price=Decimal("99"),
    )

    assert [fill.price for fill in plan.fills] == [Decimal("100"), Decimal("101")]
    assert plan.total_notional == Decimal("302")
    assert plan.vwap == Decimal("302") / Decimal("3")
    assert plan.slippage.book_slippage_amount == Decimal("2")
    assert plan.slippage.price_drift == Decimal("1")
    assert plan.slippage.total_slippage_amount == Decimal("5")
    assert plan.slippage.reference_notional == Decimal("297")
    assert plan.slippage.slippage_rate == Decimal("5") / Decimal("297")


def test_ex_003_multi_level_market_sell_and_favorable_drift() -> None:
    plan = match_market_order(
        book(bids=(("102", "1"), ("101", "2"), ("100", "3"))),
        side=OrderSide.SELL,
        quantity=Decimal("3"),
        submission_reference_price=Decimal("101"),
    )

    assert [fill.price for fill in plan.fills] == [Decimal("102"), Decimal("101")]
    assert plan.vwap == Decimal("304") / Decimal("3")
    assert plan.slippage.book_slippage_amount == Decimal("2")
    assert plan.slippage.price_drift == Decimal("-1")
    assert plan.slippage.total_slippage_amount == Decimal("-1")


def test_ex_004_insufficient_depth_returns_partial_fill() -> None:
    plan = match_market_order(
        book(asks=(("100", "1"), ("101", "1"))),
        side=OrderSide.BUY,
        quantity=Decimal("3"),
        submission_reference_price=Decimal("100"),
    )

    assert plan.status is MatchStatus.PARTIALLY_FILLED
    assert plan.filled_quantity == Decimal("2")
    assert plan.remaining_quantity == Decimal("1")


def test_zero_liquidity_has_no_vwap_or_slippage() -> None:
    plan = match_market_order(
        book(asks=()),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        submission_reference_price=Decimal("100"),
    )

    assert plan.status is MatchStatus.NO_FILL
    assert plan.vwap is None
    assert plan.slippage.book_slippage_amount is None
    assert plan.slippage.total_slippage_amount is None
    assert plan.slippage.slippage_rate is None


def test_missing_submission_reference_keeps_total_slippage_null() -> None:
    plan = match_market_order(
        book(asks=(("100", "1"), ("101", "1"))),
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        submission_reference_price=None,
    )

    assert plan.slippage.book_slippage_amount == Decimal("1")
    assert plan.slippage.price_drift is None
    assert plan.slippage.total_slippage_amount is None


@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-1")])
def test_quantity_must_be_positive(quantity: Decimal) -> None:
    with pytest.raises(ValueError, match="positive"):
        match_market_order(
            book(),
            side=OrderSide.BUY,
            quantity=quantity,
            submission_reference_price=Decimal("100"),
        )


def test_quantity_must_be_decimal() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        match_market_order(
            book(),
            side=OrderSide.BUY,
            quantity=1,  # type: ignore[arg-type]
            submission_reference_price=Decimal("100"),
        )
