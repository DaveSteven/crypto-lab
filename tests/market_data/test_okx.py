from decimal import Decimal

import pytest

from crypto_lab.market_data import normalize_okx_order_book
from crypto_lab.models import OrderBookDelta, OrderBookSnapshot
from crypto_lab.trading import normalize_okx_spot_rules


def snapshot_payload() -> dict[str, object]:
    return {
        "arg": {"channel": "books", "instId": "BTC-USDT"},
        "action": "snapshot",
        "data": [
            {
                "asks": [["101", "2", "0", "1"], ["102", "3", "0", "2"]],
                "bids": [["100", "4", "0", "2"], ["99", "5", "0", "3"]],
                "ts": "1000",
                "checksum": 0,
                "prevSeqId": -1,
                "seqId": 10,
            }
        ],
    }


def test_okx_books_snapshot_normalizes_to_canonical_event() -> None:
    event = normalize_okx_order_book(snapshot_payload(), received_ts_ms=1_001)

    assert isinstance(event.payload, OrderBookSnapshot)
    assert event.instrument_id == "okx:SPOT:BTC/USDT"
    assert event.exchange_ts_ms == 1_000
    assert event.payload.sequence_id == "10"
    assert event.payload.checksum is None
    assert event.payload.bids[0].price == Decimal("100")
    assert event.payload.asks[0].quantity == Decimal("2")


def test_okx_books_update_preserves_zero_quantity_and_sequences() -> None:
    payload = snapshot_payload()
    payload["action"] = "update"
    item = payload["data"][0]  # type: ignore[index]
    item["bids"] = [["100", "0", "0", "0"]]  # type: ignore[index]
    item["asks"] = []  # type: ignore[index]
    item["prevSeqId"] = 10  # type: ignore[index]
    item["seqId"] = 11  # type: ignore[index]

    event = normalize_okx_order_book(payload, received_ts_ms=1_001)

    assert isinstance(event.payload, OrderBookDelta)
    assert event.payload.bid_updates[0].quantity == 0
    assert event.payload.previous_sequence_id == "10"
    assert event.payload.last_sequence_id == "11"


def test_okx_normalizer_rejects_wrong_channel_or_invalid_values() -> None:
    wrong_channel = snapshot_payload()
    wrong_channel["arg"] = {"channel": "books5", "instId": "BTC-USDT"}
    with pytest.raises(ValueError, match="books channel"):
        normalize_okx_order_book(wrong_channel, received_ts_ms=1_001)

    invalid = snapshot_payload()
    invalid["data"][0]["asks"][0][1] = "bad"  # type: ignore[index]
    with pytest.raises(ValueError, match="decimal"):
        normalize_okx_order_book(invalid, received_ts_ms=1_001)


def test_okx_spot_instrument_rules_are_explicit_and_versioned() -> None:
    rules = normalize_okx_spot_rules(
        {
            "code": "0",
            "msg": "",
            "data": [
                {
                    "instType": "SPOT",
                    "instId": "BTC-USDT",
                    "state": "live",
                    "tickSz": "0.1",
                    "lotSz": "0.00000001",
                    "minSz": "0.00001",
                }
            ],
        },
        instrument="BTC-USDT",
        observed_ts_ms=1_000,
    )

    assert rules.rules_id == "OKX:PUBLIC_INSTRUMENTS:BTC-USDT:1000"
    assert rules.price_increment == Decimal("0.1")
    assert rules.quantity_increment == Decimal("0.00000001")
    assert rules.min_quantity == Decimal("0.00001")
    assert rules.min_notional is None


@pytest.mark.parametrize("state", ["suspend", "preopen", "post_only"])
def test_okx_non_live_instrument_rules_are_rejected(state: str) -> None:
    payload = {
        "code": "0",
        "data": [
            {
                "instType": "SPOT",
                "instId": "BTC-USDT",
                "state": state,
                "tickSz": "0.1",
                "lotSz": "0.00000001",
                "minSz": "0.00001",
            }
        ],
    }
    with pytest.raises(ValueError, match="live"):
        normalize_okx_spot_rules(payload, instrument="BTC-USDT", observed_ts_ms=1_000)
