#!/usr/bin/env python3
"""Fetch and normalize one live ticker from each Phase 0 exchange."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from crypto_lab.market_data import normalize_ticker
from crypto_lab.models import ExchangeId


@dataclass(frozen=True)
class TickerEndpoint:
    exchange_id: ExchangeId
    base_asset: str
    quote_asset: str
    url: str


ENDPOINTS: Final = (
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


def default_output_path() -> Path:
    utc_now = datetime.now(UTC)
    return (
        Path("data/normalized")
        / f"{utc_now:%Y-%m-%d}"
        / f"ticker-rest-{utc_now:%H%M%S}.jsonl"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")

    output_path = args.output or default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    failures = 0
    for endpoint in ENDPOINTS:
        try:
            raw, received_ts_ms = fetch_json(endpoint, args.timeout)
            record = normalize_ticker(
                endpoint.exchange_id,
                endpoint.base_asset,
                endpoint.quote_asset,
                raw,
                received_ts_ms,
                raw_ref=endpoint.url,
            )
            records.append(record)
            print(
                f"PASS {endpoint.exchange_id.value:8} {record.instrument_id:27} "
                f"quality={record.quality_status.value}"
            )
        except (KeyError, IndexError, TypeError, ValueError, urllib.error.URLError) as exc:
            failures += 1
            print(f"FAIL {endpoint.exchange_id.value:8} {type(exc).__name__}: {exc}")

    with output_path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(record.model_dump_json() + "\n")
    print(f"\n{len(records)}/{len(ENDPOINTS)} normalized; evidence: {output_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
