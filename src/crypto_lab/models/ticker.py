"""Canonical ticker payload."""

from decimal import Decimal

from pydantic import Field

from crypto_lab.models.common import CanonicalModel


class Ticker(CanonicalModel):
    bid: Decimal | None = Field(default=None, gt=0)
    bid_size: Decimal | None = Field(default=None, ge=0)
    ask: Decimal | None = Field(default=None, gt=0)
    ask_size: Decimal | None = Field(default=None, ge=0)
    last: Decimal | None = Field(default=None, gt=0)
    open_24h: Decimal | None = Field(default=None, gt=0)
    high_24h: Decimal | None = Field(default=None, gt=0)
    low_24h: Decimal | None = Field(default=None, gt=0)
    base_volume_24h: Decimal | None = Field(default=None, ge=0)
    quote_volume_24h: Decimal | None = Field(default=None, ge=0)
