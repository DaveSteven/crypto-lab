"""Exchange-specific raw ticker adapters into the canonical schema."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from crypto_lab.models.common import MarketEventEnvelope
from crypto_lab.models.enums import (
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketType,
    TransportType,
)
from crypto_lab.models.ticker import Ticker

RawPayload = dict[str, Any]


def decimal_or_none(value: object) -> Decimal | None:
    """Convert raw JSON values without ever constructing Decimal from float."""

    if value is None or value == "":
        return None
    if isinstance(value, float):
        raise TypeError("float input would lose the original decimal representation")
    return Decimal(str(value))


def iso8601_to_epoch_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return int(parsed.astimezone(UTC).timestamp() * 1000)


def canonical_symbol(base_asset: str, quote_asset: str) -> str:
    base = base_asset.strip().upper()
    quote = quote_asset.strip().upper()
    if not base or not quote or "/" in base or "/" in quote:
        raise ValueError("base and quote assets must be non-empty asset identifiers")
    return f"{base}/{quote}"


def instrument_id(exchange_id: ExchangeId, base_asset: str, quote_asset: str) -> str:
    symbol = canonical_symbol(base_asset, quote_asset)
    return f"{exchange_id.value}:{MarketType.SPOT.value}:{symbol}"


def _binance(raw: RawPayload) -> tuple[Ticker, int | None]:
    return (
        Ticker(
            bid=decimal_or_none(raw.get("bidPrice")),
            bid_size=decimal_or_none(raw.get("bidQty")),
            ask=decimal_or_none(raw.get("askPrice")),
            ask_size=decimal_or_none(raw.get("askQty")),
        ),
        None,
    )


def _okx(raw: RawPayload) -> tuple[Ticker, int | None]:
    item = raw["data"][0]
    return (
        Ticker(
            bid=decimal_or_none(item.get("bidPx")),
            bid_size=decimal_or_none(item.get("bidSz")),
            ask=decimal_or_none(item.get("askPx")),
            ask_size=decimal_or_none(item.get("askSz")),
            last=decimal_or_none(item.get("last")),
            open_24h=decimal_or_none(item.get("open24h")),
            high_24h=decimal_or_none(item.get("high24h")),
            low_24h=decimal_or_none(item.get("low24h")),
            base_volume_24h=decimal_or_none(item.get("vol24h")),
            quote_volume_24h=decimal_or_none(item.get("volCcy24h")),
        ),
        int(item["ts"]),
    )


def _bybit(raw: RawPayload) -> tuple[Ticker, int | None]:
    item = raw["result"]["list"][0]
    return (
        Ticker(
            bid=decimal_or_none(item.get("bid1Price")),
            bid_size=decimal_or_none(item.get("bid1Size")),
            ask=decimal_or_none(item.get("ask1Price")),
            ask_size=decimal_or_none(item.get("ask1Size")),
            last=decimal_or_none(item.get("lastPrice")),
            high_24h=decimal_or_none(item.get("highPrice24h")),
            low_24h=decimal_or_none(item.get("lowPrice24h")),
            base_volume_24h=decimal_or_none(item.get("volume24h")),
            quote_volume_24h=decimal_or_none(item.get("turnover24h")),
        ),
        int(raw["time"]),
    )


def _kraken(raw: RawPayload) -> tuple[Ticker, int | None]:
    item = next(iter(raw["result"].values()))
    return (
        Ticker(
            bid=decimal_or_none(item["b"][0]),
            bid_size=decimal_or_none(item["b"][2]),
            ask=decimal_or_none(item["a"][0]),
            ask_size=decimal_or_none(item["a"][2]),
            last=decimal_or_none(item["c"][0]),
            open_24h=decimal_or_none(item["o"]),
            high_24h=decimal_or_none(item["h"][1]),
            low_24h=decimal_or_none(item["l"][1]),
            base_volume_24h=decimal_or_none(item["v"][1]),
        ),
        None,
    )


def _coinbase(raw: RawPayload) -> tuple[Ticker, int | None]:
    return (
        Ticker(
            bid=decimal_or_none(raw.get("bid")),
            ask=decimal_or_none(raw.get("ask")),
            last=decimal_or_none(raw.get("price")),
            base_volume_24h=decimal_or_none(raw.get("volume")),
        ),
        iso8601_to_epoch_ms(raw["time"]),
    )


def _bitbank(raw: RawPayload) -> tuple[Ticker, int | None]:
    item = raw["data"]
    return (
        Ticker(
            bid=decimal_or_none(item.get("buy")),
            ask=decimal_or_none(item.get("sell")),
            last=decimal_or_none(item.get("last")),
            open_24h=decimal_or_none(item.get("open")),
            high_24h=decimal_or_none(item.get("high")),
            low_24h=decimal_or_none(item.get("low")),
            base_volume_24h=decimal_or_none(item.get("vol")),
        ),
        int(item["timestamp"]),
    )


NORMALIZERS: dict[ExchangeId, Callable[[RawPayload], tuple[Ticker, int | None]]] = {
    ExchangeId.BINANCE: _binance,
    ExchangeId.OKX: _okx,
    ExchangeId.BYBIT: _bybit,
    ExchangeId.KRAKEN: _kraken,
    ExchangeId.COINBASE: _coinbase,
    ExchangeId.BITBANK: _bitbank,
}


def ticker_quality(ticker: Ticker) -> DataQualityStatus:
    if ticker.bid is None or ticker.ask is None:
        return DataQualityStatus.INCOMPLETE
    if ticker.bid > ticker.ask:
        return DataQualityStatus.INVALID
    return DataQualityStatus.VALID


def normalize_ticker(
    exchange_id: ExchangeId,
    base_asset: str,
    quote_asset: str,
    raw: RawPayload,
    received_ts_ms: int,
    raw_ref: str | None = None,
) -> MarketEventEnvelope[Ticker]:
    ticker, exchange_ts_ms = NORMALIZERS[exchange_id](raw)
    return MarketEventEnvelope[Ticker](
        event_id=str(uuid4()),
        event_type="TICKER",
        exchange_id=exchange_id,
        instrument_id=instrument_id(exchange_id, base_asset, quote_asset),
        source_type=DataSourceType.LIVE,
        transport=TransportType.REST,
        exchange_ts_ms=exchange_ts_ms,
        received_ts_ms=received_ts_ms,
        processed_ts_ms=time_ms(),
        raw_ref=raw_ref,
        quality_status=ticker_quality(ticker),
        payload=ticker,
    )


def time_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)
