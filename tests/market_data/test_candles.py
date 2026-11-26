from crypto_lab.market_data import normalize_okx_rest_candles, normalize_okx_websocket_candles
from crypto_lab.models import TransportType

ROWS = [
    ["60000", "100.1", "102.2", "99.9", "101.3", "1.25", "1.25", "126.0", "0"],
    ["120000", "101.3", "103", "101", "102", "2", "2", "204", "1"],
]


def test_okx_rest_candles_normalize_sort_and_deduplicate() -> None:
    events = normalize_okx_rest_candles(
        {"code": "0", "data": [ROWS[1], ROWS[0], ROWS[0]]},
        instrument_id="okx:SPOT:BTC/USDT",
        interval="1m",
        received_ts_ms=1_000,
    )
    assert [item.payload.open_ts_ms for item in events] == [60_000, 120_000]
    assert events[0].transport is TransportType.REST
    assert not events[0].payload.is_closed
    assert events[1].payload.is_closed


def test_okx_websocket_candle_uses_real_confirm_and_interval() -> None:
    events = normalize_okx_websocket_candles(
        {
            "arg": {"channel": "candle1m", "instId": "BTC-USDT"},
            "data": [ROWS[0]],
        },
        received_ts_ms=2_000,
    )
    assert events[0].instrument_id == "okx:SPOT:BTC/USDT"
    assert events[0].payload.interval == "1m"
    assert events[0].transport is TransportType.WEBSOCKET


def test_different_intervals_have_distinct_channels() -> None:
    one_minute = normalize_okx_websocket_candles(
        {"arg": {"channel": "candle1m", "instId": "BTC-USDT"}, "data": [ROWS[0]]},
        received_ts_ms=2_000,
    )[0]
    one_day_row = ["86400000", *ROWS[0][1:]]
    one_day = normalize_okx_websocket_candles(
        {
            "arg": {"channel": "candle1Dutc", "instId": "BTC-USDT"},
            "data": [one_day_row],
        },
        received_ts_ms=2_000,
    )[0]
    assert one_minute.payload.interval == "1m"
    assert one_day.payload.interval == "1d"
