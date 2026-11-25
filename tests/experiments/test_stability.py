import json
from decimal import Decimal

import pytest

from crypto_lab.experiments.stability import (
    GrossSpreadEpisodes,
    RotatingJsonlWriter,
    StorageLimitReachedError,
)
from crypto_lab.models import DataQualityStatus, ExchangeId, SpreadObservation


def observation(gross_spread: str) -> SpreadObservation:
    return SpreadObservation(
        observation_id="obs",
        canonical_symbol="BTC/USDT",
        buy_exchange_id=ExchangeId.BINANCE,
        sell_exchange_id=ExchangeId.OKX,
        buy_event_id="buy",
        sell_event_id="sell",
        buy_ask="100",
        sell_bid=str(Decimal("100") + Decimal(gross_spread)),
        observed_ts_ms=1_000,
        buy_quote_age_ms=0,
        sell_quote_age_ms=0,
        timestamp_basis="received_ts_ms",
        gross_spread=gross_spread,
        gross_spread_rate=Decimal(gross_spread) / Decimal("100"),
        quality_status=DataQualityStatus.VALID,
    )


def test_writer_rotates_and_preserves_jsonl(tmp_path) -> None:
    writer = RotatingJsonlWriter(tmp_path, "sample", rotate_bytes=20, max_bytes=100)
    writer.write({"value": "first"})
    writer.write({"value": "second"})
    writer.close()

    files = sorted(tmp_path.glob("*.jsonl"))
    assert len(files) == 2
    assert json.loads(files[0].read_text())["value"] == "first"


def test_writer_stops_before_storage_limit(tmp_path) -> None:
    with pytest.raises(ValueError, match="storage limits"):
        RotatingJsonlWriter(tmp_path, "sample", rotate_bytes=50, max_bytes=20)


def test_writer_raises_when_accumulated_data_exceeds_limit(tmp_path) -> None:
    writer = RotatingJsonlWriter(tmp_path, "sample", rotate_bytes=20, max_bytes=40)
    writer.write({"v": "1234567890"})
    with pytest.raises(StorageLimitReachedError):
        writer.write({"v": "1234567890"})
        writer.write({"v": "1234567890"})


def test_positive_spread_episode_closes_when_spread_turns_negative() -> None:
    tracker = GrossSpreadEpisodes(max_gap_ms=2_000)
    tracker.observe([observation("1")], 1_000)
    tracker.observe([observation("1")], 2_000)
    tracker.observe([observation("-1")], 3_000)

    assert tracker.completed_count == 1
    assert tracker.completed_duration_ms == 1_000
