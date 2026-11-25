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


class TimeInForce(StrEnum):
    GTC = "GTC"


class OrderStatus(StrEnum):
    PENDING_EXECUTION = "PENDING_EXECUTION"
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
    time_in_force: TimeInForce = TimeInForce.GTC
    fee_schedule_id: str | None = Field(default=None, min_length=1)
    reserved_fee_rate: Decimal = Field(default=Decimal(0), ge=0, le=1)
    status: OrderStatus
    submitted_ts_ms: int = Field(ge=0)
    scheduled_execution_ts_ms: int | None = Field(default=None, ge=0)
    market_entry_ts_ms: int | None = Field(default=None, ge=0)
    executed_ts_ms: int | None = Field(default=None, ge=0)
    configured_latency_ms: int | None = Field(default=None, ge=0)
    actual_simulated_delay_ms: int | None = Field(default=None, ge=0)
    scheduler_lag_ms: int | None = Field(default=None, ge=0)
    submission_quote_event_id: str | None = Field(default=None, min_length=1)
    execution_quote_event_id: str | None = Field(default=None, min_length=1)
    termination_reason: str | None = Field(default=None, min_length=1)
    order_sequence: int = Field(gt=0)
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
        if self.market_entry_ts_ms is not None and self.market_entry_ts_ms < self.submitted_ts_ms:
            raise ValueError("market entry time cannot precede submission time")
        if (
            self.scheduled_execution_ts_ms is not None
            and self.scheduled_execution_ts_ms < self.submitted_ts_ms
        ):
            raise ValueError("scheduled execution cannot precede submission")
        if self.configured_latency_ms is not None:
            expected = self.submitted_ts_ms + self.configured_latency_ms
            if self.scheduled_execution_ts_ms != expected:
                raise ValueError(
                    "scheduled execution must equal submission plus configured latency"
                )
        if self.executed_ts_ms is not None:
            if self.scheduled_execution_ts_ms is None:
                raise ValueError("executed order requires a scheduled execution time")
            if self.executed_ts_ms < self.scheduled_execution_ts_ms:
                raise ValueError("execution cannot precede scheduled execution")
            expected_delay = self.executed_ts_ms - self.submitted_ts_ms
            if self.actual_simulated_delay_ms != expected_delay:
                raise ValueError("actual simulated delay is inconsistent with execution time")
            expected_lag = self.executed_ts_ms - self.scheduled_execution_ts_ms
            if self.scheduler_lag_ms != expected_lag:
                raise ValueError("scheduler lag is inconsistent with execution time")
        elif self.actual_simulated_delay_ms is not None:
            raise ValueError("actual simulated delay requires execution time")
        elif self.scheduler_lag_ms is not None:
            raise ValueError("scheduler lag requires execution time")
        if self.status is OrderStatus.PENDING_EXECUTION:
            if self.scheduled_execution_ts_ms is None or self.configured_latency_ms is None:
                raise ValueError("pending execution requires schedule metadata")
            if self.market_entry_ts_ms is not None:
                raise ValueError("pending execution order cannot have entered the market")
        if self.created_ts_ms != self.submitted_ts_ms:
            raise ValueError("created time must equal submission time")
        return self
