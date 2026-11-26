"""OKX public spot order-book normalization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from crypto_lab.market_data.normalizers import ticker_quality
from crypto_lab.models import (
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketEventEnvelope,
    OrderBookDelta,
    OrderBookSnapshot,
    PriceLevel,
    Ticker,
    Trade,
    TradeSide,
    TransportType,
)


def normalize_okx_tickers(
    payload: object,
    *,
    received_ts_ms: int,
    source_type: DataSourceType = DataSourceType.LIVE,
    raw_ref: str | None = None,
) -> MarketEventEnvelope[Ticker]:
    message = _mapping(payload, "OKX message")
    argument = _mapping(message.get("arg"), "OKX message arg")
    if argument.get("channel") != "tickers":
        raise ValueError("OKX ticker normalizer requires tickers channel")
    subscribed_instrument = _required_string(argument, "instId")
    instrument_id = _canonical_spot_instrument(subscribed_instrument)
    rows = _sequence(message.get("data"), "OKX message data")
    if len(rows) != 1:
        raise ValueError("OKX tickers message must contain exactly one data item")
    item = _mapping(rows[0], "OKX tickers data item")
    if item.get("instId") != subscribed_instrument:
        raise ValueError("OKX ticker item instrument differs from subscription")
    exchange_ts_ms = _required_nonnegative_int_string(item, "ts")
    ticker = Ticker(
        bid=_optional_decimal(item.get("bidPx")),
        bid_size=_optional_nonnegative_decimal(item.get("bidSz")),
        ask=_optional_decimal(item.get("askPx")),
        ask_size=_optional_nonnegative_decimal(item.get("askSz")),
        last=_optional_decimal(item.get("last")),
        open_24h=_optional_decimal(item.get("open24h")),
        high_24h=_optional_decimal(item.get("high24h")),
        low_24h=_optional_decimal(item.get("low24h")),
        base_volume_24h=_optional_nonnegative_decimal(item.get("vol24h")),
        quote_volume_24h=_optional_nonnegative_decimal(item.get("volCcy24h")),
    )
    return MarketEventEnvelope[Ticker](
        event_id=f"okx:{subscribed_instrument}:ticker:{exchange_ts_ms}",
        event_type="TICKER",
        exchange_id=ExchangeId.OKX,
        instrument_id=instrument_id,
        source_type=source_type,
        transport=TransportType.WEBSOCKET,
        exchange_ts_ms=exchange_ts_ms,
        received_ts_ms=received_ts_ms,
        raw_ref=raw_ref,
        quality_status=ticker_quality(ticker),
        payload=ticker,
    )


def normalize_okx_order_book(
    payload: object,
    *,
    received_ts_ms: int,
    source_type: DataSourceType = DataSourceType.LIVE,
    raw_ref: str | None = None,
) -> MarketEventEnvelope[OrderBookSnapshot] | MarketEventEnvelope[OrderBookDelta]:
    message = _mapping(payload, "OKX message")
    argument = _mapping(message.get("arg"), "OKX message arg")
    if argument.get("channel") != "books":
        raise ValueError("OKX order-book normalizer requires books channel")
    instrument = _required_string(argument, "instId")
    instrument_id = _canonical_spot_instrument(instrument)
    action = message.get("action")
    if action not in {"snapshot", "update"}:
        raise ValueError("OKX books message requires snapshot or update action")
    data = _sequence(message.get("data"), "OKX message data")
    if len(data) != 1:
        raise ValueError("OKX books message must contain exactly one data item")
    item = _mapping(data[0], "OKX books data item")
    sequence_id = _required_string_or_int(item, "seqId")
    exchange_ts_ms = _required_nonnegative_int_string(item, "ts")
    bids = _levels(item.get("bids"), "bids")
    asks = _levels(item.get("asks"), "asks")

    common: dict[str, Any] = {
        "event_id": str(uuid4()),
        "exchange_id": ExchangeId.OKX,
        "instrument_id": instrument_id,
        "source_type": source_type,
        "transport": TransportType.WEBSOCKET,
        "exchange_ts_ms": exchange_ts_ms,
        "received_ts_ms": received_ts_ms,
        "raw_ref": raw_ref,
        "quality_status": DataQualityStatus.VALID,
    }
    if action == "snapshot":
        return MarketEventEnvelope[OrderBookSnapshot](
            **common,
            event_type="ORDER_BOOK_SNAPSHOT",
            payload=OrderBookSnapshot(
                bids=bids,
                asks=asks,
                depth=400,
                sequence_id=sequence_id,
                checksum=None,
                synchronized=True,
            ),
        )
    return MarketEventEnvelope[OrderBookDelta](
        **common,
        event_type="ORDER_BOOK_DELTA",
        payload=OrderBookDelta(
            bid_updates=bids,
            ask_updates=asks,
            previous_sequence_id=_required_string_or_int(item, "prevSeqId"),
            last_sequence_id=sequence_id,
            checksum=None,
        ),
    )


def normalize_okx_trades(
    payload: object,
    *,
    received_ts_ms: int,
    source_type: DataSourceType = DataSourceType.LIVE,
    raw_ref: str | None = None,
) -> tuple[MarketEventEnvelope[Trade], ...]:
    """Normalize every aggregate in an OKX public ``trades`` message.

    OKX defines ``side`` as the taker side. The public channel can aggregate
    several matches at the same price into one item; its ``sz`` is therefore
    retained as the single allocatable quantity and ``tradeId`` as its source
    identity.
    """

    message = _mapping(payload, "OKX message")
    argument = _mapping(message.get("arg"), "OKX message arg")
    if argument.get("channel") != "trades":
        raise ValueError("OKX trade normalizer requires trades channel")
    subscribed_instrument = _required_string(argument, "instId")
    instrument_id = _canonical_spot_instrument(subscribed_instrument)
    rows = _sequence(message.get("data"), "OKX message data")
    if not rows:
        raise ValueError("OKX trades message must contain at least one data item")

    events: list[MarketEventEnvelope[Trade]] = []
    for index, row in enumerate(rows):
        item = _mapping(row, "OKX trades data item")
        instrument = _required_string(item, "instId")
        if instrument != subscribed_instrument:
            raise ValueError("OKX trade item instrument differs from subscription")
        trade_id = _required_string(item, "tradeId")
        side = _trade_side(_required_string(item, "side"))
        exchange_ts_ms = _required_nonnegative_int_string(item, "ts")
        events.append(
            MarketEventEnvelope[Trade](
                event_id=f"okx:{instrument}:trade:{trade_id}:{exchange_ts_ms}:{index}",
                event_type="TRADE",
                exchange_id=ExchangeId.OKX,
                instrument_id=instrument_id,
                source_type=source_type,
                transport=TransportType.WEBSOCKET,
                exchange_ts_ms=exchange_ts_ms,
                received_ts_ms=received_ts_ms,
                raw_ref=raw_ref,
                quality_status=DataQualityStatus.VALID,
                payload=Trade(
                    trade_id=trade_id,
                    price=_positive_decimal(item.get("px"), "trade price"),
                    quantity=_positive_decimal(item.get("sz"), "trade quantity"),
                    side=side,
                ),
            )
        )
    return tuple(events)


def _levels(value: object, name: str) -> tuple[PriceLevel, ...]:
    rows = _sequence(value, f"OKX {name}")
    levels: list[PriceLevel] = []
    for row in rows:
        values = _sequence(row, f"OKX {name} level")
        if len(values) < 2:
            raise ValueError(f"OKX {name} level requires price and quantity")
        levels.append(
            PriceLevel(
                price=_positive_decimal(values[0], f"{name} price"),
                quantity=_nonnegative_decimal(values[1], f"{name} quantity"),
            )
        )
    return tuple(levels)


def _canonical_spot_instrument(instrument: str) -> str:
    parts = instrument.split("-")
    if len(parts) != 2 or not all(parts):
        raise ValueError("OKX SPOT instrument must contain base and quote currencies")
    return f"okx:SPOT:{parts[0]}/{parts[1]}"


def _trade_side(value: str) -> TradeSide:
    if value == "buy":
        return TradeSide.BUY
    if value == "sell":
        return TradeSide.SELL
    raise ValueError("OKX trade side must be buy or sell")


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _sequence(value: object, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be an array")
    return value


def _required_string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise ValueError(f"OKX {field} must be a non-empty string")
    return result


def _required_string_or_int(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if isinstance(result, bool) or not isinstance(result, (str, int)):
        raise ValueError(f"OKX {field} must be a string or integer")
    text = str(result)
    if not text:
        raise ValueError(f"OKX {field} cannot be empty")
    return text


def _required_nonnegative_int_string(value: Mapping[str, Any], field: str) -> int:
    result = _required_string_or_int(value, field)
    try:
        parsed = int(result)
    except ValueError as exc:
        raise ValueError(f"OKX {field} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"OKX {field} cannot be negative")
    return parsed


def _positive_decimal(value: object, name: str) -> Decimal:
    result = _decimal(value, name)
    if result <= 0:
        raise ValueError(f"OKX {name} must be positive")
    return result


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    result = _decimal(value, "optional price")
    if result <= 0:
        raise ValueError("OKX optional price must be positive when present")
    return result


def _optional_nonnegative_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    result = _decimal(value, "optional size")
    if result < 0:
        raise ValueError("OKX optional size cannot be negative when present")
    return result


def _nonnegative_decimal(value: object, name: str) -> Decimal:
    result = _decimal(value, name)
    if result < 0:
        raise ValueError(f"OKX {name} cannot be negative")
    return result


def _decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise TypeError(f"OKX {name} must be a decimal string or integer")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"OKX {name} is not a decimal") from exc
