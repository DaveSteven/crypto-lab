import pytest

from crypto_lab.market_data import InvalidOrderBookStateError, OrderBookMarketState
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

INSTRUMENT = "okx:SPOT:BTC/USDT"


def snapshot_event(
    *,
    sequence: str = "10",
    received_ts_ms: int = 1_000,
    quality: DataQualityStatus = DataQualityStatus.VALID,
    synchronized: bool = True,
) -> MarketEventEnvelope[OrderBookSnapshot]:
    return MarketEventEnvelope[OrderBookSnapshot](
        event_id=f"snapshot-{sequence}",
        event_type="ORDER_BOOK_SNAPSHOT",
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        source_type=DataSourceType.MOCK,
        transport=TransportType.FILE,
        received_ts_ms=received_ts_ms,
        quality_status=quality,
        payload=OrderBookSnapshot(
            bids=[PriceLevel(price="100", quantity="2")],
            asks=[PriceLevel(price="101", quantity="3")],
            depth=20,
            sequence_id=sequence,
            synchronized=synchronized,
        ),
    )


def delta_event(
    *, previous: str = "10", current: str = "11"
) -> MarketEventEnvelope[OrderBookDelta]:
    return MarketEventEnvelope[OrderBookDelta](
        event_id=f"delta-{current}",
        event_type="ORDER_BOOK_DELTA",
        exchange_id=ExchangeId.OKX,
        instrument_id=INSTRUMENT,
        source_type=DataSourceType.MOCK,
        transport=TransportType.FILE,
        received_ts_ms=1_001,
        quality_status=DataQualityStatus.VALID,
        payload=OrderBookDelta(
            bid_updates=[PriceLevel(price="100", quantity="0")],
            ask_updates=[PriceLevel(price="101", quantity="4")],
            previous_sequence_id=previous,
            last_sequence_id=current,
        ),
    )


def test_snapshot_and_absolute_delta_build_executable_state() -> None:
    state = OrderBookMarketState()
    state.apply_snapshot(snapshot_event())
    updated = state.apply_delta(delta_event())

    assert updated.bids == ()
    assert updated.asks[0].quantity == 4
    assert updated.sequence_id == "11"

    with pytest.raises(InvalidOrderBookStateError, match="both sides"):
        state.executable_book(
            ExchangeId.OKX,
            INSTRUMENT,
            decision_ts_ms=1_001,
            max_age_ms=2_000,
        )


def test_sequence_gap_invalidates_state_until_new_snapshot() -> None:
    state = OrderBookMarketState()
    state.apply_snapshot(snapshot_event())

    with pytest.raises(InvalidOrderBookStateError, match="sequence gap"):
        state.apply_delta(delta_event(previous="9"))
    with pytest.raises(InvalidOrderBookStateError, match="quality"):
        state.executable_book(
            ExchangeId.OKX,
            INSTRUMENT,
            decision_ts_ms=1_001,
            max_age_ms=2_000,
        )

    state.apply_snapshot(snapshot_event(sequence="20", received_ts_ms=1_002))
    assert (
        state.executable_book(
            ExchangeId.OKX,
            INSTRUMENT,
            decision_ts_ms=1_002,
            max_age_ms=2_000,
        ).sequence_id
        == "20"
    )


@pytest.mark.parametrize(
    ("decision_ts_ms", "max_age_ms", "message"),
    [(999, 2_000, "after decision"), (3_001, 2_000, "stale")],
)
def test_future_and_stale_books_are_not_executable(
    decision_ts_ms: int, max_age_ms: int, message: str
) -> None:
    state = OrderBookMarketState()
    state.apply_snapshot(snapshot_event())

    with pytest.raises(InvalidOrderBookStateError, match=message):
        state.executable_book(
            ExchangeId.OKX,
            INSTRUMENT,
            decision_ts_ms=decision_ts_ms,
            max_age_ms=max_age_ms,
        )


def test_invalid_unsynchronized_and_disconnected_books_are_rejected() -> None:
    state = OrderBookMarketState()
    state.apply_snapshot(snapshot_event(quality=DataQualityStatus.INVALID))
    with pytest.raises(InvalidOrderBookStateError, match="quality"):
        state.executable_book(ExchangeId.OKX, INSTRUMENT, decision_ts_ms=1_000, max_age_ms=2_000)

    state.apply_snapshot(snapshot_event(sequence="20", synchronized=False))
    with pytest.raises(InvalidOrderBookStateError, match="not synchronized"):
        state.executable_book(ExchangeId.OKX, INSTRUMENT, decision_ts_ms=1_000, max_age_ms=2_000)

    state.apply_snapshot(snapshot_event(sequence="30"))
    state.mark_disconnected(ExchangeId.OKX, INSTRUMENT)
    with pytest.raises(InvalidOrderBookStateError, match="disconnected"):
        state.executable_book(ExchangeId.OKX, INSTRUMENT, decision_ts_ms=1_000, max_age_ms=2_000)
