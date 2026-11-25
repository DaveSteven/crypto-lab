"""Immutable paper-account and ledger data models."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from crypto_lab.models import ExchangeId


class LedgerReason(StrEnum):
    INITIAL_FUNDING = "INITIAL_FUNDING"
    ORDER_RESERVE = "ORDER_RESERVE"
    ORDER_RELEASE = "ORDER_RELEASE"
    TRADE_SETTLEMENT = "TRADE_SETTLEMENT"
    FEE = "FEE"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PaperAccount(FrozenModel):
    account_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    exchange_id: ExchangeId
    created_ts_ms: int = Field(ge=0)


class AssetBalance(FrozenModel):
    asset: str = Field(min_length=1)
    available: Decimal = Field(ge=0)
    locked: Decimal = Field(ge=0)

    @field_validator("asset")
    @classmethod
    def normalize_asset(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized or "/" in normalized:
            raise ValueError("asset must be a single asset identifier")
        return normalized

    @property
    def total(self) -> Decimal:
        return self.available + self.locked


class LedgerEntry(FrozenModel):
    entry_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    exchange_id: ExchangeId
    asset: str = Field(min_length=1)
    available_delta: Decimal = Decimal(0)
    locked_delta: Decimal = Decimal(0)
    reason: LedgerReason
    reference_id: str | None = Field(default=None, min_length=1)
    created_ts_ms: int = Field(ge=0)

    @field_validator("asset")
    @classmethod
    def normalize_asset(cls, value: str) -> str:
        return AssetBalance.normalize_asset(value)

    @model_validator(mode="after")
    def require_non_zero_change(self) -> "LedgerEntry":
        if self.available_delta == 0 and self.locked_delta == 0:
            raise ValueError("ledger entry must change at least one balance")
        return self


def utc_now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)
