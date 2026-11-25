"""Canonical order-book payloads."""

from decimal import Decimal

from pydantic import Field, model_validator

from crypto_lab.models.common import CanonicalModel


class PriceLevel(CanonicalModel):
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(ge=0)


class OrderBookSnapshot(CanonicalModel):
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    depth: int = Field(gt=0)
    sequence_id: str | None = Field(default=None, min_length=1)
    checksum: str | None = Field(default=None, min_length=1)
    synchronized: bool

    @model_validator(mode="after")
    def validate_levels(self) -> "OrderBookSnapshot":
        _validate_snapshot_side(self.bids, descending=True, name="bids")
        _validate_snapshot_side(self.asks, descending=False, name="asks")
        if len(self.bids) > self.depth or len(self.asks) > self.depth:
            raise ValueError("order-book levels cannot exceed declared depth")
        if self.bids and self.asks and self.bids[0].price >= self.asks[0].price:
            raise ValueError("order book must not be crossed or locked")
        return self


class OrderBookDelta(CanonicalModel):
    bid_updates: tuple[PriceLevel, ...]
    ask_updates: tuple[PriceLevel, ...]
    first_sequence_id: str | None = Field(default=None, min_length=1)
    last_sequence_id: str | None = Field(default=None, min_length=1)
    previous_sequence_id: str | None = Field(default=None, min_length=1)
    checksum: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_updates(self) -> "OrderBookDelta":
        _validate_unique_prices(self.bid_updates, "bid updates")
        _validate_unique_prices(self.ask_updates, "ask updates")
        return self


def _validate_snapshot_side(
    levels: tuple[PriceLevel, ...],
    *,
    descending: bool,
    name: str,
) -> None:
    if any(level.quantity <= 0 for level in levels):
        raise ValueError(f"snapshot {name} require positive quantity")
    _validate_unique_prices(levels, name)
    pairs = zip(levels, levels[1:], strict=False)
    if descending and any(left.price <= right.price for left, right in pairs):
        raise ValueError("snapshot bids must be sorted by descending price")
    if not descending and any(left.price >= right.price for left, right in pairs):
        raise ValueError("snapshot asks must be sorted by ascending price")


def _validate_unique_prices(levels: tuple[PriceLevel, ...], name: str) -> None:
    prices = {level.price for level in levels}
    if len(prices) != len(levels):
        raise ValueError(f"{name} must not contain duplicate prices")
