"""Canonical public market-trade payload."""

from decimal import Decimal

from pydantic import Field

from crypto_lab.models.common import CanonicalModel
from crypto_lab.models.enums import TradeSide


class Trade(CanonicalModel):
    trade_id: str | None = Field(default=None, min_length=1)
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    quote_amount: Decimal | None = Field(default=None, gt=0)
    side: TradeSide
