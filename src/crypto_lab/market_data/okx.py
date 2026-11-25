"""OKX public spot order-book normalization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from crypto_lab.models import (
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketEventEnvelope,
    OrderBookDelta,
    OrderBookSnapshot,
    PriceLevel,
    TransportType,
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
