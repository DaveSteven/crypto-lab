"""External REST schemas, deliberately separate from domain models."""

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

DecimalString = Annotated[Decimal, PlainSerializer(str, return_type=str)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnvironmentCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    client_reference_id: str | None = Field(default=None, min_length=1, max_length=100)


class AccountCreate(ApiModel):
    exchange_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    initial_asset: str = Field(min_length=1, max_length=32)
    initial_amount: DecimalString

    @field_validator("initial_amount", mode="before")
    @classmethod
    def decimal_string(cls, value: object) -> Decimal:
        if not isinstance(value, str):
            raise ValueError("Decimal values must be JSON strings")
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid Decimal string") from exc
        if not parsed.is_finite() or parsed <= 0:
            raise ValueError("initial_amount must be positive and finite")
        return parsed


class OrderCreate(ApiModel):
    account_id: str = Field(min_length=1, max_length=64)
    instrument_id: str = Field(
        pattern=r"^[a-z0-9_-]+:SPOT:[A-Z0-9]+/[A-Z0-9]+$", max_length=100
    )
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT"]
    quantity: DecimalString
    limit_price: DecimalString | None = None
    max_quote_budget: DecimalString | None = None
    latency_preset: Literal["IDEAL", "FAST", "NORMAL", "MEDIUM", "SLOW", "HIGH", "CUSTOM"] = (
        "NORMAL"
    )
    custom_latency_ms: int | None = Field(default=None, ge=0, le=60_000)

    @field_validator("quantity", "limit_price", "max_quote_budget", mode="before")
    @classmethod
    def positive_decimal_string(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Decimal values must be JSON strings")
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid Decimal string") from exc
        if not parsed.is_finite() or parsed <= 0:
            raise ValueError("Decimal values must be positive and finite")
        return parsed

    @model_validator(mode="after")
    def validate_order_intent(self) -> "OrderCreate":
        if self.order_type == "LIMIT" and self.limit_price is None:
            raise ValueError("limit_price is required for LIMIT orders")
        if self.order_type == "MARKET" and self.limit_price is not None:
            raise ValueError("limit_price is not valid for MARKET orders")
        if self.side == "BUY" and self.order_type == "MARKET":
            if self.max_quote_budget is None:
                raise ValueError("max_quote_budget is required for market buys")
        elif self.max_quote_budget is not None:
            raise ValueError("max_quote_budget is only valid for market buys")
        if self.latency_preset == "CUSTOM" and self.custom_latency_ms is None:
            raise ValueError("custom_latency_ms is required for CUSTOM latency")
        if self.latency_preset != "CUSTOM" and self.custom_latency_ms is not None:
            raise ValueError("custom_latency_ms is only valid for CUSTOM latency")
        return self


class ErrorBody(ApiModel):
    code: str
    message: str
    details: dict[str, object]
    request_id: str


class ErrorResponse(ApiModel):
    error: ErrorBody
