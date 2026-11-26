"""Connected-instrument listing and per-instrument market rules (Task 1.12.10-A audit)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from crypto_lab.api.app import _rules_for_instruments, create_app
from crypto_lab.api.market_feed import OKX_SPOT_RULES, MarketFeedSettings
from crypto_lab.realtime import EnvironmentMarketDispatcher
from crypto_lab.trading import FeeSchedule


class _Feed:
    async def run(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _Service:
    def get_environment(self, environment_id: str) -> dict:
        return {"environment_id": environment_id}


def test_endpoint_lists_only_configured_feed_instruments() -> None:
    app = create_app(
        service=_Service(),
        market_feed=_Feed(),
        market_feed_settings=MarketFeedSettings(
            enabled=True, instruments=("okx:SPOT:BTC/USDT", "okx:SPOT:ETH/USDT")
        ),
    )
    with TestClient(app) as client:
        body = client.get("/api/v1/market/instruments").json()
    assert body["feed_enabled"] is True
    assert [i["instrument_id"] for i in body["items"]] == [
        "okx:SPOT:BTC/USDT",
        "okx:SPOT:ETH/USDT",
    ]
    assert body["items"][1] == {
        "instrument_id": "okx:SPOT:ETH/USDT",
        "exchange_id": "okx",
        "market_type": "SPOT",
        "base_asset": "ETH",
        "quote_asset": "USDT",
    }


def test_disabled_feed_lists_nothing() -> None:
    app = create_app(service=_Service(), market_feed_settings=MarketFeedSettings(enabled=False))
    with TestClient(app) as client:
        body = client.get("/api/v1/market/instruments").json()
    assert body == {"feed_enabled": False, "items": []}


def test_rules_are_per_instrument_and_never_shared() -> None:
    btc = OKX_SPOT_RULES["okx:SPOT:BTC/USDT"]
    eth = OKX_SPOT_RULES["okx:SPOT:ETH/USDT"]
    assert btc.price_increment == Decimal("0.1")
    assert eth.price_increment == Decimal("0.01")
    assert eth.quantity_increment == Decimal("0.000001")
    assert eth.min_quantity == Decimal("0.0001")


def test_feed_instrument_without_verified_rules_is_refused() -> None:
    with pytest.raises(RuntimeError, match="no verified market rules"):
        _rules_for_instruments(("okx:SPOT:DOGE/USDT",))


def test_dispatcher_requires_rules_for_every_instrument_and_resolves_per_instrument() -> None:
    fees = FeeSchedule(
        schedule_id="t", maker_rate=Decimal("0.001"), taker_rate=Decimal("0.001")
    )
    common = {
        "transaction": lambda _e: None,
        "environment_exists": lambda _e: True,
        "fee_schedule": fees,
        "now_ms": lambda: 0,
    }
    with pytest.raises(ValueError, match="missing"):
        EnvironmentMarketDispatcher(
            instruments=("okx:SPOT:BTC/USDT", "okx:SPOT:ETH/USDT"),
            market_rules={"okx:SPOT:BTC/USDT": OKX_SPOT_RULES["okx:SPOT:BTC/USDT"]},
            **common,
        )
    dispatcher = EnvironmentMarketDispatcher(
        instruments=("okx:SPOT:BTC/USDT", "okx:SPOT:ETH/USDT"),
        market_rules=dict(OKX_SPOT_RULES),
        **common,
    )
    assert dispatcher._rules_for("okx:SPOT:ETH/USDT").price_increment == Decimal("0.01")
    assert dispatcher._rules_for("okx:SPOT:BTC/USDT").price_increment == Decimal("0.1")
