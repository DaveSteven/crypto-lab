from decimal import Decimal

import pytest
from pydantic import ValidationError

from crypto_lab.models import Candle


def candle(**overrides):
    values = {
        "interval": "1m",
        "open_ts_ms": 60_000,
        "close_ts_ms": 120_000,
        "open": "100.1",
        "high": "102.2",
        "low": "99.9",
        "close": "101.3",
        "base_volume": "1.234567890123456789",
        "quote_volume": "123.45",
        "is_closed": False,
    }
    values.update(overrides)
    return Candle(**values)


def test_candle_preserves_decimal_precision_and_boundaries() -> None:
    result = candle()
    assert result.base_volume == Decimal("1.234567890123456789")
    assert result.close_ts_ms - result.open_ts_ms == 60_000


@pytest.mark.parametrize(
    "overrides",
    [
        {"high": "100"},
        {"low": "101.4"},
        {"close_ts_ms": 120_001},
        {"open_ts_ms": 60_001, "close_ts_ms": 120_001},
        {"interval": "3m"},
    ],
)
def test_candle_rejects_invalid_ohlc_and_intervals(overrides) -> None:
    with pytest.raises(ValidationError):
        candle(**overrides)
