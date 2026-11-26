"""OKX public REST and WebSocket adapters for real Canonical Candle data."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from crypto_lab.models import (
    CANDLE_INTERVAL_MS,
    Candle,
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketEventEnvelope,
    TransportType,
)

OKX_BAR = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1Dutc"}
OKX_CHANNEL = {interval: f"candle{bar}" for interval, bar in OKX_BAR.items()}


class OkxCandleClient:
    def __init__(
        self, *, base_url: str = "https://www.okx.com", timeout_seconds: float = 5
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def history(
        self,
        instrument_id: str,
        interval: str,
        *,
        limit: int = 100,
        before: int | None = None,
        after: int | None = None,
    ) -> tuple[MarketEventEnvelope[Candle], ...]:
        instrument = _okx_instrument(instrument_id)
        if interval not in OKX_BAR:
            raise ValueError("unsupported candle interval")
        if not 1 <= limit <= 300:
            raise ValueError("candle limit must be between 1 and 300")
        parameters = {"instId": instrument, "bar": OKX_BAR[interval], "limit": str(limit)}
        if before is not None:
            parameters["before"] = str(before)
        if after is not None:
            parameters["after"] = str(after)
        url = f"{self.base_url}/api/v5/market/history-candles?{urllib.parse.urlencode(parameters)}"
        request = urllib.request.Request(
            url, headers={"User-Agent": "crypto-lab/0.1 (+public-candle-research)"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("candle response exceeded 2000000 bytes")
        received_ts_ms = time.time_ns() // 1_000_000
        payload = json.loads(body)
        return normalize_okx_rest_candles(
            payload,
            instrument_id=instrument_id,
            interval=interval,
            received_ts_ms=received_ts_ms,
        )


def normalize_okx_rest_candles(
    payload: object,
    *,
    instrument_id: str,
    interval: str,
    received_ts_ms: int,
) -> tuple[MarketEventEnvelope[Candle], ...]:
    message = _mapping(payload, "OKX candle response")
    if message.get("code") != "0":
        raise ValueError("OKX candle request failed")
    rows = _sequence(message.get("data"), "OKX candle data")
    events = [
        _event(
            row,
            instrument_id=instrument_id,
            interval=interval,
            received_ts_ms=received_ts_ms,
            transport=TransportType.REST,
        )
        for row in rows
    ]
    unique: dict[tuple[int, str], MarketEventEnvelope[Candle]] = {}
    for event in events:
        unique[(event.payload.open_ts_ms, event.payload.interval)] = event
    return tuple(sorted(unique.values(), key=lambda item: item.payload.open_ts_ms))


def normalize_okx_websocket_candles(
    payload: object, *, received_ts_ms: int
) -> tuple[MarketEventEnvelope[Candle], ...]:
    message = _mapping(payload, "OKX candle message")
    argument = _mapping(message.get("arg"), "OKX candle arg")
    channel = argument.get("channel")
    reverse_channels = {value: key for key, value in OKX_CHANNEL.items()}
    if channel not in reverse_channels:
        raise ValueError("unsupported OKX candle channel")
    instrument = argument.get("instId")
    if not isinstance(instrument, str):
        raise ValueError("OKX candle instId is required")
    instrument_id = f"okx:SPOT:{instrument.replace('-', '/')}"
    return tuple(
        _event(
            row,
            instrument_id=instrument_id,
            interval=reverse_channels[channel],
            received_ts_ms=received_ts_ms,
            transport=TransportType.WEBSOCKET,
        )
        for row in _sequence(message.get("data"), "OKX candle data")
    )


def _event(
    row: object,
    *,
    instrument_id: str,
    interval: str,
    received_ts_ms: int,
    transport: TransportType,
) -> MarketEventEnvelope[Candle]:
    values = _sequence(row, "OKX candle row")
    if len(values) < 9:
        raise ValueError("OKX candle row requires 9 fields")
    open_ts_ms = _integer(values[0], "open time")
    duration = CANDLE_INTERVAL_MS.get(interval)
    if duration is None:
        raise ValueError("unsupported candle interval")
    candle = Candle(
        interval=interval,
        open_ts_ms=open_ts_ms,
        close_ts_ms=open_ts_ms + duration,
        open=_decimal(values[1], "open"),
        high=_decimal(values[2], "high"),
        low=_decimal(values[3], "low"),
        close=_decimal(values[4], "close"),
        base_volume=_nonnegative_decimal(values[5], "base volume"),
        quote_volume=_nonnegative_decimal(values[7], "quote volume"),
        is_closed=values[8] == "1",
    )
    if values[8] not in {"0", "1"}:
        raise ValueError("OKX candle confirm must be 0 or 1")
    return MarketEventEnvelope[Candle](
        event_id=f"okx:{instrument_id}:candle:{interval}:{open_ts_ms}:{values[8]}",
        event_type="CANDLE",
        exchange_id=ExchangeId.OKX,
        instrument_id=instrument_id,
        source_type=DataSourceType.LIVE,
        transport=transport,
        exchange_ts_ms=open_ts_ms,
        received_ts_ms=received_ts_ms,
        quality_status=DataQualityStatus.VALID,
        payload=candle,
    )


def _okx_instrument(instrument_id: str) -> str:
    if not instrument_id.startswith("okx:SPOT:"):
        raise ValueError("only OKX SPOT candles are supported")
    symbol = instrument_id.removeprefix("okx:SPOT:")
    if "/" not in symbol:
        raise ValueError("invalid canonical instrument")
    return symbol.replace("/", "-")


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _sequence(value: object, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be an array")
    return value


def _integer(value: object, name: str) -> int:
    if not isinstance(value, str):
        raise TypeError(f"OKX candle {name} must be a string")
    try:
        result = int(value)
    except ValueError as exc:
        raise ValueError(f"OKX candle {name} must be an integer") from exc
    if result < 0:
        raise ValueError(f"OKX candle {name} cannot be negative")
    return result


def _decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str):
        raise TypeError(f"OKX candle {name} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"OKX candle {name} is invalid") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"OKX candle {name} must be positive and finite")
    return result


def _nonnegative_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str):
        raise TypeError(f"OKX candle {name} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"OKX candle {name} is invalid") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"OKX candle {name} must be nonnegative and finite")
    return result
