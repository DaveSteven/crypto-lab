"""Canonical OHLCV candlestick payload."""

from decimal import Decimal

from pydantic import Field, model_validator

from crypto_lab.models.common import CanonicalModel

CANDLE_INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class Candle(CanonicalModel):
    interval: str
    open_ts_ms: int = Field(ge=0)
    close_ts_ms: int = Field(gt=0)
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    base_volume: Decimal | None = Field(default=None, ge=0)
    quote_volume: Decimal | None = Field(default=None, ge=0)
    trade_count: int | None = Field(default=None, ge=0)
    is_closed: bool

    @model_validator(mode="after")
    def validate_candle(self) -> "Candle":
        duration = CANDLE_INTERVAL_MS.get(self.interval)
        if duration is None:
            raise ValueError("unsupported candle interval")
        if self.close_ts_ms != self.open_ts_ms + duration:
            raise ValueError("candle boundaries do not match interval")
        if self.open_ts_ms % duration != 0:
            raise ValueError("candle open time is not aligned to interval")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("candle high is below an OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("candle low is above an OHLC value")
        return self
