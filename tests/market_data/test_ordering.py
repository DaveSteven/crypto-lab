from crypto_lab.market_data.ordering import EventSequenceTracker
from crypto_lab.models import (
    DataQualityStatus,
    DataSourceType,
    EventOrderingResult,
    ExchangeId,
    MarketEventEnvelope,
    Ticker,
    TransportType,
)


def event(event_id: str, exchange_ts_ms: int) -> MarketEventEnvelope[Ticker]:
    return MarketEventEnvelope[Ticker](
        event_id=event_id,
        event_type="TICKER",
        exchange_id=ExchangeId.OKX,
        instrument_id="okx:SPOT:BTC/USDT",
        source_type=DataSourceType.MOCK,
        transport=TransportType.FILE,
        exchange_ts_ms=exchange_ts_ms,
        received_ts_ms=exchange_ts_ms,
        quality_status=DataQualityStatus.VALID,
        payload=Ticker(bid="100", ask="101"),
    )


def test_duplicate_event_is_rejected() -> None:
    tracker = EventSequenceTracker()
    sample = event("same-id", 1_000)

    assert tracker.observe(sample) is EventOrderingResult.ACCEPTED
    assert tracker.observe(sample) is EventOrderingResult.DUPLICATE


def test_older_exchange_timestamp_is_out_of_order() -> None:
    tracker = EventSequenceTracker()

    assert tracker.observe(event("newer", 2_000)) is EventOrderingResult.ACCEPTED
    assert tracker.observe(event("older", 1_000)) is EventOrderingResult.OUT_OF_ORDER


def test_duplicate_cache_is_bounded() -> None:
    tracker = EventSequenceTracker(max_event_ids=1)

    assert tracker.observe(event("first", 1_000)) is EventOrderingResult.ACCEPTED
    assert tracker.observe(event("second", 2_000)) is EventOrderingResult.ACCEPTED
    assert tracker.observe(event("first", 3_000)) is EventOrderingResult.ACCEPTED
