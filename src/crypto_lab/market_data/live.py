"""Bounded public REST retrieval used by Phase 0 live ticker experiments."""

import json
import time
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from crypto_lab.models import ExchangeId


@dataclass(frozen=True)
class TickerEndpoint:
    exchange_id: ExchangeId
    base_asset: str
    quote_asset: str
    url: str


TICKER_ENDPOINTS: Final = (
    TickerEndpoint(
        ExchangeId.BINANCE,
        "BTC",
        "USDT",
        "https://api.binance.com/api/v3/ticker/bookTicker?symbol=BTCUSDT",
    ),
    TickerEndpoint(
        ExchangeId.OKX,
        "BTC",
        "USDT",
        "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT",
    ),
    TickerEndpoint(
        ExchangeId.BYBIT,
        "BTC",
        "USDT",
        "https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT",
    ),
    TickerEndpoint(
        ExchangeId.KRAKEN,
        "BTC",
        "USDT",
        "https://api.kraken.com/0/public/Ticker?pair=XBTUSDT",
    ),
    TickerEndpoint(
        ExchangeId.COINBASE,
        "BTC",
        "USDT",
        "https://api.exchange.coinbase.com/products/BTC-USDT/ticker",
    ),
    TickerEndpoint(
        ExchangeId.BITBANK,
        "BTC",
        "JPY",
        "https://public.bitbank.cc/btc_jpy/ticker",
    ),
)


def fetch_json(endpoint: TickerEndpoint, timeout_seconds: float) -> tuple[dict, int]:
    request = urllib.request.Request(
        endpoint.url,
        headers={"User-Agent": "crypto-lab-phase0/0.1 (+ticker-normalization)"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("response exceeded 2000000 bytes")
        received_ts_ms = time.time_ns() // 1_000_000
        payload = json.loads(body, parse_float=Decimal)
        if not isinstance(payload, dict):
            raise ValueError("ticker response must be a JSON object")
        return payload, received_ts_ms
