from decimal import Decimal

import pytest

from crypto_lab.market_data.normalizers import (
    canonical_symbol,
    decimal_or_none,
    normalize_ticker,
)
from crypto_lab.models import DataQualityStatus, ExchangeId


def test_binance_ticker_normalizes_decimal_strings_and_missing_last() -> None:
    event = normalize_ticker(
        ExchangeId.BINANCE,
        "btc",
        "usdt",
        {
            "bidPrice": "100.10",
            "bidQty": "2.5",
            "askPrice": "100.20",
            "askQty": "1.75",
        },
        received_ts_ms=1_000,
    )

    assert event.instrument_id == "binance:SPOT:BTC/USDT"
    assert event.exchange_ts_ms is None
    assert event.payload.bid == Decimal("100.10")
    assert event.payload.last is None
    assert event.quality_status is DataQualityStatus.VALID
    assert '"bid":"100.10"' in event.model_dump_json()


def test_crossed_quote_is_invalid() -> None:
    event = normalize_ticker(
        ExchangeId.BINANCE,
        "BTC",
        "USDT",
        {
            "bidPrice": "101",
            "bidQty": "1",
            "askPrice": "100",
            "askQty": "1",
        },
        received_ts_ms=1_000,
    )

    assert event.quality_status is DataQualityStatus.INVALID


def test_missing_executable_quote_is_incomplete() -> None:
    event = normalize_ticker(
        ExchangeId.BINANCE,
        "BTC",
        "USDT",
        {"bidPrice": None, "bidQty": None, "askPrice": "100", "askQty": "1"},
        received_ts_ms=1_000,
    )

    assert event.quality_status is DataQualityStatus.INCOMPLETE


def test_float_input_is_rejected_before_decimal_conversion() -> None:
    with pytest.raises(TypeError, match="float input"):
        decimal_or_none(0.1)


@pytest.mark.parametrize(
    ("base", "quote", "expected"),
    [("btc", "usdt", "BTC/USDT"), (" ETH ", "jpy", "ETH/JPY")],
)
def test_canonical_symbol(base: str, quote: str, expected: str) -> None:
    assert canonical_symbol(base, quote) == expected


@pytest.mark.parametrize(
    ("exchange_id", "raw", "expected_bid", "expected_exchange_ts"),
    [
        (
            ExchangeId.OKX,
            {
                "data": [
                    {
                        "bidPx": "100",
                        "bidSz": "1",
                        "askPx": "101",
                        "askSz": "2",
                        "last": "100.5",
                        "ts": "900",
                    }
                ]
            },
            Decimal("100"),
            900,
        ),
        (
            ExchangeId.BYBIT,
            {
                "time": 901,
                "result": {
                    "list": [
                        {
                            "bid1Price": "100",
                            "bid1Size": "1",
                            "ask1Price": "101",
                            "ask1Size": "2",
                            "lastPrice": "100.5",
                        }
                    ]
                },
            },
            Decimal("100"),
            901,
        ),
        (
            ExchangeId.KRAKEN,
            {
                "result": {
                    "XBTUSDT": {
                        "b": ["100", "1", "1"],
                        "a": ["101", "1", "2"],
                        "c": ["100.5", "0.1"],
                        "o": "99",
                        "h": ["102", "103"],
                        "l": ["98", "97"],
                        "v": ["10", "20"],
                    }
                }
            },
            Decimal("100"),
            None,
        ),
        (
            ExchangeId.COINBASE,
            {
                "bid": "100",
                "ask": "101",
                "price": "100.5",
                "volume": "10",
                "time": "1970-01-01T00:00:00.902Z",
            },
            Decimal("100"),
            902,
        ),
        (
            ExchangeId.BITBANK,
            {
                "data": {
                    "buy": "100",
                    "sell": "101",
                    "last": "100.5",
                    "open": "99",
                    "high": "102",
                    "low": "98",
                    "vol": "10",
                    "timestamp": 903,
                }
            },
            Decimal("100"),
            903,
        ),
    ],
)
def test_exchange_ticker_shapes(
    exchange_id: ExchangeId,
    raw: dict,
    expected_bid: Decimal,
    expected_exchange_ts: int | None,
) -> None:
    quote = "JPY" if exchange_id is ExchangeId.BITBANK else "USDT"
    event = normalize_ticker(exchange_id, "BTC", quote, raw, received_ts_ms=1_000)

    assert event.payload.bid == expected_bid
    assert event.exchange_ts_ms == expected_exchange_ts
    assert event.quality_status is DataQualityStatus.VALID
