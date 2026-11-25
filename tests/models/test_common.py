import pytest
from pydantic import ValidationError

from crypto_lab.models import (
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketEventEnvelope,
    Ticker,
    TransportType,
)


def envelope(**overrides: object) -> MarketEventEnvelope[Ticker]:
    values = {
        "event_id": "event-1",
        "event_type": "TICKER",
        "exchange_id": ExchangeId.OKX,
        "instrument_id": "okx:SPOT:BTC/USDT",
        "source_type": DataSourceType.MOCK,
        "transport": TransportType.FILE,
        "received_ts_ms": 1_000,
        "processed_ts_ms": 1_001,
        "quality_status": DataQualityStatus.VALID,
        "payload": Ticker(bid="100", ask="101"),
    }
    values.update(overrides)
    return MarketEventEnvelope[Ticker](**values)


def test_processed_time_cannot_precede_received_time() -> None:
    with pytest.raises(ValidationError, match="cannot precede"):
        envelope(processed_ts_ms=999)


def test_instrument_must_belong_to_exchange() -> None:
    with pytest.raises(ValidationError, match="belong to exchange"):
        envelope(instrument_id="bybit:SPOT:BTC/USDT")
