from decimal import Decimal

from crypto_lab.market_data import OrderBookView
from crypto_lab.models import DataQualityStatus, ExchangeId, PriceLevel
from crypto_lab.trading import MatchStatus, match_market_buy_with_budget


def book(*asks: tuple[str, str]) -> OrderBookView:
    return OrderBookView(
        exchange_id=ExchangeId.OKX,
        instrument_id="okx:SPOT:BTC/USDT",
        bids=(PriceLevel(price="99", quantity="10"),),
        asks=tuple(PriceLevel(price=price, quantity=quantity) for price, quantity in asks),
        depth=len(asks),
        sequence_id="1",
        source_event_id="book-1",
        exchange_ts_ms=1_000,
        received_ts_ms=1_001,
        quality_status=DataQualityStatus.VALID,
        synchronized=True,
        source_connected=True,
    )


def match(view: OrderBookView, *, budget: str, fee: str = "0.01"):
    return match_market_buy_with_budget(
        view,
        quantity=Decimal("3"),
        max_quote_budget=Decimal(budget),
        fee_rate=Decimal(fee),
        quantity_increment=Decimal("0.1"),
        min_quantity=Decimal("0.1"),
        min_notional=Decimal("10"),
        submission_reference_price=Decimal("100"),
    )


def test_budget_sufficient_for_full_multilevel_fill() -> None:
    plan = match(book(("100", "1"), ("101", "2")), budget="305.02")

    assert plan.status is MatchStatus.FILLED
    assert [fill.quantity for fill in plan.fills] == [Decimal("1"), Decimal("2")]
    assert plan.total_notional == Decimal("302")


def test_budget_includes_fee_and_floors_last_level_to_quantity_step() -> None:
    plan = match(book(("100", "1"), ("101", "2")), budget="254.015")

    assert plan.status is MatchStatus.PARTIALLY_FILLED
    assert [fill.quantity for fill in plan.fills] == [Decimal("1"), Decimal("1.5")]
    assert plan.total_notional == Decimal("251.5")
    assert plan.total_notional * Decimal("1.01") <= Decimal("254.015")


def test_budget_that_cannot_fund_minimum_legal_fill_returns_no_fill() -> None:
    plan = match(
        book(
            ("100", "1"),
        ),
        budget="10",
    )

    assert plan.status is MatchStatus.NO_FILL
    assert plan.fills == ()
    assert plan.remaining_quantity == Decimal("3")
