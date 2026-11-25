"""Canonical enumerations for Phase 0 market data."""

from enum import StrEnum


class ExchangeId(StrEnum):
    BINANCE = "binance"
    OKX = "okx"
    BYBIT = "bybit"
    KRAKEN = "kraken"
    COINBASE = "coinbase"
    BITBANK = "bitbank"


class MarketType(StrEnum):
    SPOT = "SPOT"


class DataSourceType(StrEnum):
    LIVE = "LIVE"
    HISTORICAL = "HISTORICAL"
    MOCK = "MOCK"
    SYNTHETIC = "SYNTHETIC"


class TradeSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    UNKNOWN = "UNKNOWN"


class TransportType(StrEnum):
    REST = "REST"
    WEBSOCKET = "WEBSOCKET"
    FILE = "FILE"


class DataQualityStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    STALE = "STALE"
    INCOMPLETE = "INCOMPLETE"
    UNSYNCED = "UNSYNCED"


class EventOrderingResult(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
