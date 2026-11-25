"""Paper spot-order models and state definitions."""

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from crypto_lab.trading.models import FrozenModel


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


class PaperOrder(FrozenModel):
    order_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    instrument_id: str = Field(pattern=r"^[a-z0-9_-]+:SPOT:[A-Z0-9]+/[A-Z0-9]+$")
    side: OrderSide
    order_type: OrderType
    quantity: Decimal = Field(gt=0)
    limit_price: Decimal | None = Field(default=None, gt=0)
    reference_price: Decimal = Field(gt=0)
    reserved_asset: str = Field(min_length=1)
    reserved_amount: Decimal = Field(gt=0)
    filled_quantity: Decimal = Field(default=Decimal(0), ge=0)
    cumulative_quote_amount: Decimal = Field(default=Decimal(0), ge=0)
    cumulative_fee: Decimal = Field(default=Decimal(0), ge=0)
    average_fill_price: Decimal | None = Field(default=None, gt=0)
    status: OrderStatus
    created_ts_ms: int = Field(ge=0)
    updated_ts_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> "PaperOrder":
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market orders cannot define limit_price")
        if self.filled_quantity > self.quantity:
            raise ValueError("filled quantity cannot exceed requested quantity")
        if self.filled_quantity == 0 and self.average_fill_price is not None:
            raise ValueError("unfilled order cannot have an average fill price")
        if self.filled_quantity > 0 and self.average_fill_price is None:
            raise ValueError("filled order requires an average fill price")
        return self
