from decimal import Decimal

import pytest
from pydantic import ValidationError

from crypto_lab.models import OrderBookDelta, OrderBookSnapshot, PriceLevel


def level(price: str, quantity: str = "1") -> PriceLevel:
    return PriceLevel(price=price, quantity=quantity)


def test_snapshot_accepts_sorted_non_crossed_levels() -> None:
    book = OrderBookSnapshot(
        bids=[level("100"), level("99")],
        asks=[level("101"), level("102")],
        depth=2,
        sequence_id="10",
        synchronized=True,
    )

    assert book.bids[0].price == Decimal("100")
    assert book.asks[0].price == Decimal("101")


@pytest.mark.parametrize(
    ("bids", "asks", "message"),
    [
        ([level("99"), level("100")], [level("101")], "descending"),
        ([level("100")], [level("102"), level("101")], "ascending"),
        ([level("100"), level("100")], [level("101")], "duplicate"),
        ([level("101")], [level("101")], "crossed or locked"),
        ([level("100", "0")], [level("101")], "positive quantity"),
    ],
)
def test_snapshot_rejects_invalid_depth(
    bids: list[PriceLevel], asks: list[PriceLevel], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        OrderBookSnapshot(
            bids=bids,
            asks=asks,
            depth=2,
            synchronized=True,
        )


def test_delta_allows_zero_quantity_deletions_but_not_duplicate_prices() -> None:
    delta = OrderBookDelta(
        bid_updates=[level("100", "0")],
        ask_updates=[level("101", "2")],
        previous_sequence_id="10",
        last_sequence_id="11",
    )
    assert delta.bid_updates[0].quantity == 0

    with pytest.raises(ValidationError, match="duplicate"):
        OrderBookDelta(
            bid_updates=[level("100"), level("100", "2")],
            ask_updates=[],
        )
