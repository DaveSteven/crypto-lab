from decimal import Decimal

import pytest

from crypto_lab.market_data import OrderBookView
from crypto_lab.models import DataQualityStatus, ExchangeId, PriceLevel
from crypto_lab.trading import (
    MarketRules,
    MarketRuleViolation,
    OrderSide,
    match_market_order,
)


def plan(quantity: str = "0.002", price: str = "50000"):
    book = OrderBookView(
        exchange_id=ExchangeId.OKX,
        instrument_id="okx:SPOT:BTC/USDT",
        bids=(PriceLevel(price="49999", quantity="1"),),
        asks=(PriceLevel(price=price, quantity="1"),),
        depth=20,
        sequence_id="1",
        source_event_id="book-1",
        exchange_ts_ms=1,
        received_ts_ms=1,
        quality_status=DataQualityStatus.VALID,
        synchronized=True,
        source_connected=True,
    )
    return match_market_order(
        book,
        side=OrderSide.BUY,
        quantity=Decimal(quantity),
        submission_reference_price=Decimal(price),
    )


def rules() -> MarketRules:
    return MarketRules(
        rules_id="MOCK:BTC-USDT:v1",
        price_increment=Decimal("0.01"),
        quantity_increment=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("100"),
    )


def test_market_rules_accept_aligned_order() -> None:
    rules().validate(plan())


@pytest.mark.parametrize(
    ("sample", "message"),
    [
        (plan(quantity="0.0005"), "below"),
        (plan(quantity="0.0015"), "increment"),
        (plan(quantity="0.001"), "notional"),
        (plan(price="50000.001"), "fill price"),
    ],
)
def test_market_rules_reject_invalid_order(sample, message: str) -> None:
    with pytest.raises(MarketRuleViolation, match=message):
        rules().validate(sample)
