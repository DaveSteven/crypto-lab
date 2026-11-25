"""Pure order-book matching and slippage calculations."""

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from crypto_lab.market_data.state import OrderBookView
from crypto_lab.trading.models import FrozenModel
from crypto_lab.trading.orders import OrderSide


class MatchStatus(StrEnum):
    NO_FILL = "NO_FILL"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"


class FillLeg(FrozenModel):
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    quote_amount: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def validate_quote_amount(self) -> "FillLeg":
        if self.quote_amount != self.price * self.quantity:
            raise ValueError("quote amount must equal price times quantity")
        return self


class SlippageMetrics(FrozenModel):
    submission_reference_price: Decimal | None = Field(default=None, gt=0)
    execution_reference_price: Decimal | None = Field(default=None, gt=0)
    book_slippage_amount: Decimal | None = None
    price_drift: Decimal | None = None
    total_slippage_amount: Decimal | None = None
    reference_notional: Decimal | None = Field(default=None, gt=0)
    slippage_rate: Decimal | None = None


class MatchPlan(FrozenModel):
    book_event_id: str = Field(min_length=1)
    side: OrderSide
    requested_quantity: Decimal = Field(gt=0)
    fills: tuple[FillLeg, ...]
    filled_quantity: Decimal = Field(ge=0)
    remaining_quantity: Decimal = Field(ge=0)
    total_notional: Decimal = Field(ge=0)
    vwap: Decimal | None = Field(default=None, gt=0)
    status: MatchStatus
    slippage: SlippageMetrics

    @model_validator(mode="after")
    def validate_totals(self) -> "MatchPlan":
        if self.filled_quantity + self.remaining_quantity != self.requested_quantity:
            raise ValueError("filled and remaining quantities must equal requested quantity")
        if self.filled_quantity != sum((fill.quantity for fill in self.fills), Decimal(0)):
            raise ValueError("filled quantity must equal fill-leg quantities")
        if self.total_notional != sum((fill.quote_amount for fill in self.fills), Decimal(0)):
            raise ValueError("total notional must equal fill-leg notionals")
        expected_vwap = self.total_notional / self.filled_quantity if self.filled_quantity else None
        if self.vwap != expected_vwap:
            raise ValueError("vwap must equal total notional divided by filled quantity")
        expected_status = _status(self.filled_quantity, self.requested_quantity)
        if self.status is not expected_status:
            raise ValueError("match status is inconsistent with filled quantity")
        return self


def match_market_order(
    book: OrderBookView,
    *,
    side: OrderSide,
    quantity: Decimal,
    submission_reference_price: Decimal | None,
) -> MatchPlan:
    _require_positive_decimal(quantity, "quantity")
    if submission_reference_price is not None:
        _require_positive_decimal(submission_reference_price, "submission_reference_price")

    levels = book.asks if side is OrderSide.BUY else book.bids
    execution_reference_price = levels[0].price if levels else None
    remaining = quantity
    fills: list[FillLeg] = []
    for level in levels:
        fill_quantity = min(level.quantity, remaining)
        if fill_quantity > 0:
            fills.append(
                FillLeg(
                    price=level.price,
                    quantity=fill_quantity,
                    quote_amount=level.price * fill_quantity,
                )
            )
            remaining -= fill_quantity
        if remaining == 0:
            break

    filled = quantity - remaining
    notional = sum((fill.quote_amount for fill in fills), Decimal(0))
    vwap = notional / filled if filled else None
    slippage = _slippage(
        side=side,
        fills=tuple(fills),
        filled_quantity=filled,
        vwap=vwap,
        submission_reference_price=submission_reference_price,
        execution_reference_price=execution_reference_price,
    )
    return MatchPlan(
        book_event_id=book.source_event_id,
        side=side,
        requested_quantity=quantity,
        fills=tuple(fills),
        filled_quantity=filled,
        remaining_quantity=remaining,
        total_notional=notional,
        vwap=vwap,
        status=_status(filled, quantity),
        slippage=slippage,
    )


def _slippage(
    *,
    side: OrderSide,
    fills: tuple[FillLeg, ...],
    filled_quantity: Decimal,
    vwap: Decimal | None,
    submission_reference_price: Decimal | None,
    execution_reference_price: Decimal | None,
) -> SlippageMetrics:
    if filled_quantity == 0 or vwap is None or execution_reference_price is None:
        return SlippageMetrics(
            submission_reference_price=submission_reference_price,
            execution_reference_price=execution_reference_price,
        )

    direction = Decimal(1) if side is OrderSide.BUY else Decimal(-1)
    book_slippage = direction * sum(
        ((fill.price - execution_reference_price) * fill.quantity for fill in fills),
        Decimal(0),
    )
    if submission_reference_price is None:
        return SlippageMetrics(
            execution_reference_price=execution_reference_price,
            book_slippage_amount=book_slippage,
        )

    price_drift = direction * (execution_reference_price - submission_reference_price)
    total_slippage = direction * sum(
        ((fill.price - submission_reference_price) * fill.quantity for fill in fills),
        Decimal(0),
    )
    reference_notional = submission_reference_price * filled_quantity
    return SlippageMetrics(
        submission_reference_price=submission_reference_price,
        execution_reference_price=execution_reference_price,
        book_slippage_amount=book_slippage,
        price_drift=price_drift,
        total_slippage_amount=total_slippage,
        reference_notional=reference_notional,
        slippage_rate=total_slippage / reference_notional,
    )


def _status(filled_quantity: Decimal, requested_quantity: Decimal) -> MatchStatus:
    if filled_quantity == 0:
        return MatchStatus.NO_FILL
    if filled_quantity == requested_quantity:
        return MatchStatus.FILLED
    return MatchStatus.PARTIALLY_FILLED


def _require_positive_decimal(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
