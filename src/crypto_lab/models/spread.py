"""Canonical cross-exchange spread observation."""

from decimal import Decimal

from pydantic import Field

from crypto_lab.models.common import CanonicalModel
from crypto_lab.models.enums import DataQualityStatus, ExchangeId


class SpreadObservation(CanonicalModel):
    observation_id: str = Field(min_length=1)
    canonical_symbol: str = Field(min_length=3)
    buy_exchange_id: ExchangeId
    sell_exchange_id: ExchangeId
    buy_event_id: str = Field(min_length=1)
    sell_event_id: str = Field(min_length=1)
    buy_ask: Decimal = Field(gt=0)
    sell_bid: Decimal = Field(gt=0)
    buy_available_quantity: Decimal | None = Field(default=None, ge=0)
    sell_available_quantity: Decimal | None = Field(default=None, ge=0)
    observed_ts_ms: int = Field(ge=0)
    quote_time_diff_ms: int | None = Field(default=None, ge=0)
    buy_quote_age_ms: int = Field(ge=0)
    sell_quote_age_ms: int = Field(ge=0)
    timestamp_basis: str = Field(min_length=1)
    gross_spread: Decimal
    gross_spread_rate: Decimal
    target_quantity: Decimal | None = Field(default=None, gt=0)
    estimated_executable_quantity: Decimal | None = Field(default=None, ge=0)
    estimated_buy_notional: Decimal | None = Field(default=None, ge=0)
    estimated_sell_notional: Decimal | None = Field(default=None, ge=0)
    estimated_buy_fee: Decimal | None = Field(default=None, ge=0)
    estimated_sell_fee: Decimal | None = Field(default=None, ge=0)
    estimated_execution_cost: Decimal | None = Field(default=None, ge=0)
    estimated_rebalance_cost: Decimal | None = Field(default=None, ge=0)
    estimated_net_profit: Decimal | None = None
    estimated_net_return_rate: Decimal | None = None
    cost_model_id: str | None = None
    quality_status: DataQualityStatus
