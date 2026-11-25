"""Explicit versioned paper-trading fee configuration."""

from decimal import Decimal

from pydantic import Field, model_validator

from crypto_lab.trading.models import FrozenModel


class FeeSchedule(FrozenModel):
    schedule_id: str = Field(min_length=1)
    maker_rate: Decimal = Field(ge=0, le=1)
    taker_rate: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def require_decimal_rates(self) -> "FeeSchedule":
        if not isinstance(self.maker_rate, Decimal) or not isinstance(self.taker_rate, Decimal):
            raise TypeError("fee rates must be Decimal")
        return self

    @property
    def maximum_rate(self) -> Decimal:
        return max(self.maker_rate, self.taker_rate)
