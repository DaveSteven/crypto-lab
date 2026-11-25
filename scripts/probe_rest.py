#!/usr/bin/env python3
"""Probe documented public REST market-data endpoints without credentials."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

from crypto_lab.models import APIProbeResult, TransportType

MAX_RESPONSE_BYTES: Final = 2_000_000
USER_AGENT: Final = "crypto-lab-phase0/0.1 (+public-market-data-probe)"


@dataclass(frozen=True)
class Endpoint:
    exchange_id: str
    endpoint_type: str
    url: str


def endpoints_for_asset(asset: str) -> tuple[Endpoint, ...]:
    """Build equivalent spot probes for BTC or ETH without mixing quote currencies."""

    compact_symbol = f"{asset}USDT"
    dashed_symbol = f"{asset}-USDT"
    kraken_symbol = f"{'XBT' if asset == 'BTC' else asset}USDT"
    bitbank_symbol = f"{asset.lower()}_jpy"
    utc_date = f"{datetime.now(UTC):%Y%m%d}"
    return (
        Endpoint(
            "binance",
            "instruments",
            f"https://api.binance.com/api/v3/exchangeInfo?symbol={compact_symbol}",
        ),
        Endpoint(
            "binance",
            "ticker",
            f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={compact_symbol}",
        ),
        Endpoint(
            "binance",
            "ohlcv",
            f"https://api.binance.com/api/v3/klines?symbol={compact_symbol}&interval=1m&limit=2",
        ),
        Endpoint(
            "binance",
            "order_book",
            f"https://api.binance.com/api/v3/depth?symbol={compact_symbol}&limit=5",
        ),
        Endpoint(
            "okx",
            "instruments",
            f"https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId={dashed_symbol}",
        ),
        Endpoint("okx", "ticker", f"https://www.okx.com/api/v5/market/ticker?instId={dashed_symbol}"),
        Endpoint(
            "okx",
            "ohlcv",
            f"https://www.okx.com/api/v5/market/candles?instId={dashed_symbol}&bar=1m&limit=2",
        ),
        Endpoint(
            "okx",
            "order_book",
            f"https://www.okx.com/api/v5/market/books?instId={dashed_symbol}&sz=5",
        ),
        Endpoint(
            "bybit",
            "instruments",
            "https://api.bybit.com/v5/market/instruments-info"
            f"?category=spot&symbol={compact_symbol}",
        ),
        Endpoint(
            "bybit",
            "ticker",
            f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={compact_symbol}",
        ),
        Endpoint(
            "bybit",
            "ohlcv",
            "https://api.bybit.com/v5/market/kline"
            f"?category=spot&symbol={compact_symbol}&interval=1&limit=2",
        ),
        Endpoint(
            "bybit",
            "order_book",
            "https://api.bybit.com/v5/market/orderbook"
            f"?category=spot&symbol={compact_symbol}&limit=5",
        ),
        Endpoint(
            "kraken",
            "instruments",
            f"https://api.kraken.com/0/public/AssetPairs?pair={kraken_symbol}",
        ),
        Endpoint("kraken", "ticker", f"https://api.kraken.com/0/public/Ticker?pair={kraken_symbol}"),
        Endpoint(
            "kraken",
            "ohlcv",
            f"https://api.kraken.com/0/public/OHLC?pair={kraken_symbol}&interval=1",
        ),
        Endpoint(
            "kraken",
            "order_book",
            f"https://api.kraken.com/0/public/Depth?pair={kraken_symbol}&count=5",
        ),
        Endpoint(
            "coinbase",
            "instruments",
            f"https://api.exchange.coinbase.com/products/{dashed_symbol}",
        ),
        Endpoint(
            "coinbase",
            "ticker",
            f"https://api.exchange.coinbase.com/products/{dashed_symbol}/ticker",
        ),
        Endpoint(
            "coinbase",
            "ohlcv",
            f"https://api.exchange.coinbase.com/products/{dashed_symbol}/candles?granularity=60",
        ),
        Endpoint(
            "coinbase",
            "order_book",
            f"https://api.exchange.coinbase.com/products/{dashed_symbol}/book?level=1",
        ),
        Endpoint("bitbank", "instruments", "https://api.bitbank.cc/v1/spot/pairs"),
        Endpoint("bitbank", "ticker", f"https://public.bitbank.cc/{bitbank_symbol}/ticker"),
        Endpoint(
            "bitbank",
            "ohlcv",
            f"https://public.bitbank.cc/{bitbank_symbol}/candlestick/1min/{utc_date}",
        ),
        Endpoint("bitbank", "order_book", f"https://public.bitbank.cc/{bitbank_symbol}/depth"),
    )


ENDPOINTS: Final = endpoints_for_asset("BTC") + endpoints_for_asset("ETH")


def payload_error(exchange_id: str, payload: object) -> str | None:
    """Return a documented exchange-level error hidden inside an HTTP 2xx response."""

    if exchange_id == "binance" and isinstance(payload, dict) and "code" in payload:
        return f"Binance API error: {payload.get('code')} {payload.get('msg')}"
    if exchange_id == "okx" and isinstance(payload, dict) and payload.get("code") != "0":
        return f"OKX API error: {payload.get('code')} {payload.get('msg')}"
    if exchange_id == "bybit" and isinstance(payload, dict) and payload.get("retCode") != 0:
        return f"Bybit API error: {payload.get('retCode')} {payload.get('retMsg')}"
    if exchange_id == "kraken" and isinstance(payload, dict) and payload.get("error"):
        return f"Kraken API error: {payload.get('error')}"
    if exchange_id == "coinbase" and isinstance(payload, dict) and payload.get("message"):
        return f"Coinbase API error: {payload.get('message')}"
    if exchange_id == "bitbank" and isinstance(payload, dict) and payload.get("success") != 1:
        return f"bitbank API error: {payload.get('data')}"
    return None


def probe(endpoint: Endpoint, timeout_seconds: float) -> APIProbeResult:
    """Perform one bounded request and retain its real outcome."""

    started_ts_ms = time.time_ns() // 1_000_000
    monotonic_started = time.monotonic_ns()
    status_code: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    success = False

    try:
        request = urllib.request.Request(endpoint.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = response.status
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError(f"response exceeded {MAX_RESPONSE_BYTES} bytes")
            payload = json.loads(body)
            error_message = payload_error(endpoint.exchange_id, payload)
            success = 200 <= status_code < 300 and error_message is None
            if error_message is not None:
                error_type = "ExchangeAPIError"
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        error_type = type(exc).__name__
        error_message = str(exc)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    completed_ts_ms = time.time_ns() // 1_000_000
    duration_ms = (time.monotonic_ns() - monotonic_started) // 1_000_000
    return APIProbeResult(
        probe_id=str(uuid4()),
        exchange_id=endpoint.exchange_id,
        endpoint_type=endpoint.endpoint_type,
        endpoint=endpoint.url,
        transport=TransportType.REST,
        started_ts_ms=started_ts_ms,
        completed_ts_ms=completed_ts_ms,
        duration_ms=duration_ms,
        success=success,
        status_code=status_code,
        error_type=error_type,
        error_message=error_message,
    )


def default_output_path() -> Path:
    utc_now = datetime.now(UTC)
    return Path("data/probes") / f"{utc_now:%Y-%m-%d}" / f"rest-{utc_now:%H%M%S}.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="per-request timeout in seconds"
    )
    parser.add_argument("--output", type=Path, default=None, help="JSONL evidence output path")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    output_path = args.output or default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results = [probe(endpoint, args.timeout) for endpoint in ENDPOINTS]
    with output_path.open("w", encoding="utf-8") as output:
        for result in results:
            output.write(result.model_dump_json() + "\n")
            state = "PASS" if result.success else "FAIL"
            print(
                f"{state:4} {result.exchange_id:8} {result.endpoint_type:11} "
                f"status={result.status_code!s:3} duration_ms={result.duration_ms}"
            )

    passed = sum(result.success for result in results)
    print(f"\n{passed}/{len(results)} probes succeeded; evidence: {output_path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
