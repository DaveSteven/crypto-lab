"""Service-level REST candle endpoint tests with a deterministic fake source."""

from decimal import Decimal

import pytest

from crypto_lab.api.errors import ApplicationError
from crypto_lab.api.service import ApplicationService
from crypto_lab.models import (
    CANDLE_INTERVAL_MS,
    Candle,
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketEventEnvelope,
    TransportType,
)


class FakeCandleClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, int, int | None, int | None]] = []

    def history(
        self,
        instrument_id: str,
        interval: str,
        *,
        limit: int = 100,
        before: int | None = None,
        after: int | None = None,
    ) -> tuple[MarketEventEnvelope[Candle], ...]:
        self.calls.append((instrument_id, interval, limit, before, after))
        # Mirror the real client: interval validation happens in the source.
        if interval not in CANDLE_INTERVAL_MS:
            raise ValueError("unsupported candle interval")
        if self.fail:
            raise OSError("okx unreachable")
        events = []
        for index in range(limit):
            open_ts_ms = (100 - index) * CANDLE_INTERVAL_MS[interval]
            events.append(
                MarketEventEnvelope[Candle](
                    event_id=f"okx:{instrument_id}:candle:{interval}:{open_ts_ms}:1",
                    event_type="CANDLE",
                    exchange_id=ExchangeId.OKX,
                    instrument_id=instrument_id,
                    source_type=DataSourceType.HISTORICAL,
                    transport=TransportType.REST,
                    exchange_ts_ms=open_ts_ms,
                    received_ts_ms=1_000,
                    quality_status=DataQualityStatus.VALID,
                    payload=Candle(
                        interval=interval,
                        open_ts_ms=open_ts_ms,
                        close_ts_ms=open_ts_ms + CANDLE_INTERVAL_MS[interval],
                        open=Decimal("100"),
                        high=Decimal("101"),
                        low=Decimal("99"),
                        close=Decimal("100.5"),
                        is_closed=True,
                    ),
                )
            )
        return tuple(events)


class DummyEngine:
    pass


def make_service(client) -> ApplicationService:
    return ApplicationService(DummyEngine(), candle_client=client)


def test_candle_history_returns_real_source_items() -> None:
    client = FakeCandleClient()
    service = make_service(client)
    result = service.candle_history("okx:SPOT:BTC/USDT", "1m", 5, None, None)
    assert result["source"] == "OKX_PUBLIC_REST"
    assert len(result["items"]) == 5
    assert result["items"][0]["payload"]["is_closed"] is True
    # Decimal values stay strings per the REST contract.
    assert result["items"][0]["payload"]["open"] == "100"
    assert client.calls == [("okx:SPOT:BTC/USDT", "1m", 5, None, None)]


def test_candle_history_maps_pagination_parameters() -> None:
    client = FakeCandleClient()
    service = make_service(client)
    service.candle_history("okx:SPOT:BTC/USDT", "1h", 50, before=3_600_000, after=1_000)
    assert client.calls == [("okx:SPOT:BTC/USDT", "1h", 50, 3_600_000, 1_000)]


def test_candle_history_rejects_unsupported_interval() -> None:
    service = make_service(FakeCandleClient())
    with pytest.raises(ApplicationError) as error:
        service.candle_history("okx:SPOT:BTC/USDT", "2m", 10, None, None)
    assert error.value.code == "INVALID_REQUEST"
    assert error.value.status_code == 400


def test_candle_history_requires_configured_real_source() -> None:
    service = make_service(None)
    with pytest.raises(ApplicationError) as error:
        service.candle_history("okx:SPOT:BTC/USDT", "1m", 10, None, None)
    assert error.value.code == "TOPIC_UNAVAILABLE"
    assert error.value.status_code == 503


def test_candle_history_maps_source_outage_to_unavailable() -> None:
    service = make_service(FakeCandleClient(fail=True))
    with pytest.raises(ApplicationError) as error:
        service.candle_history("okx:SPOT:BTC/USDT", "1m", 10, None, None)
    assert error.value.code == "MARKET_DATA_UNAVAILABLE"
    assert error.value.status_code == 503
