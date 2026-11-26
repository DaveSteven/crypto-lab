"""Lifespan wiring tests: the shared feed starts and stops with the app."""

import asyncio

from fastapi.testclient import TestClient

from crypto_lab.api.app import create_app
from crypto_lab.api.market_feed import MarketFeedSettings


class StubMarketFeed:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self._stopping = False

    async def run(self) -> None:
        self.started += 1
        while not self._stopping:
            await asyncio.sleep(0.01)

    async def stop(self) -> None:
        self.stopped += 1
        self._stopping = True


class StubService:
    def get_environment(self, environment_id: str) -> dict:
        return {"environment_id": environment_id}


def test_injected_feed_runs_in_lifespan_and_stops_cleanly() -> None:
    feed = StubMarketFeed()
    settings = MarketFeedSettings(enabled=True)
    app = create_app(
        service=StubService(),
        realtime=None,
        market_feed=feed,
        market_feed_settings=settings,
    )
    with TestClient(app) as client:
        assert app.state.market_feed is feed
        assert feed.started == 1
        assert client.get("/health/live").status_code == 200
    assert feed.stopped == 1


def test_disabled_settings_do_not_start_a_feed() -> None:
    app = create_app(
        service=StubService(),
        market_feed=None,
        market_feed_settings=MarketFeedSettings(enabled=False),
    )
    with TestClient(app):
        assert app.state.market_feed is None
        assert app.state.market_dispatcher is None


def test_app_state_exposes_feed_settings() -> None:
    settings = MarketFeedSettings(enabled=False)
    app = create_app(service=StubService(), market_feed_settings=settings)
    assert app.state.market_feed_settings.enabled is False


def test_feed_failure_does_not_break_rest_service() -> None:
    class BrokenFeed:
        async def run(self) -> None:
            raise RuntimeError("exchange unreachable")

        async def stop(self) -> None:
            return None

    app = create_app(
        service=StubService(),
        market_feed=BrokenFeed(),
        market_feed_settings=MarketFeedSettings(enabled=True),
    )
    with TestClient(app) as client:
        # The feed task crashed, yet REST endpoints remain available.
        assert client.get("/health/live").status_code == 200


class RecordingFeed(StubMarketFeed):
    def __init__(self, limit: int | None = None) -> None:
        super().__init__()
        self.limit = limit
        self.calls: list[tuple] = []

    async def acquire_candle(self, owner: str, instrument_id: str, interval: str) -> None:
        if self.limit is not None and len(self.calls) >= self.limit:
            from crypto_lab.realtime.feed import SubscriptionLimitError

            raise SubscriptionLimitError("limit")
        self.calls.append(("acquire", instrument_id, interval))

    def release_candle(self, owner: str, instrument_id: str, interval: str) -> None:
        self.calls.append(("release", instrument_id, interval))

    def release_owner(self, owner: str) -> None:
        self.calls.append(("owner", owner))


def _ws(client):
    return client.websocket_connect(
        "/api/v1/ws/environments/env-1",
        subprotocols=["crypto-lab.v1"],
        headers={"origin": "http://localhost:5173"},
    )


def test_ws_candle_interval_subscription_drives_feed_refs() -> None:
    feed = RecordingFeed(limit=1)
    app = create_app(
        service=StubService(),
        market_feed=feed,
        market_feed_settings=MarketFeedSettings(enabled=True),
    )
    topic = {"name": "market.candle", "instrument_id": "okx:SPOT:BTC/USDT", "interval": "5m"}
    with TestClient(app) as client, _ws(client) as ws:
        assert ws.receive_json()["type"] == "session.ready"
        ws.send_json({"type": "subscribe", "request_id": "r1", "topics": [topic]})
        assert ws.receive_json()["type"] == "subscription.ack"
        ws.send_json(
            {"type": "subscribe", "request_id": "r2", "topics": [{**topic, "interval": "1h"}]}
        )
        error = ws.receive_json()
        assert error["type"] == "error" and error["code"] == "SUBSCRIPTION_LIMIT"
        ws.send_json({"type": "unsubscribe", "request_id": "r3", "topics": [topic]})
        assert ws.receive_json()["type"] == "subscription.ack"
    kinds = [call[0] for call in feed.calls]
    assert kinds[:2] == ["acquire", "release"]
    assert kinds[-1] == "owner"


class _FakeDispatcher:
    def __init__(self, fail_on: str | None = None) -> None:
        self.registered: list[str] = []
        self.fail_on = fail_on

    def register_environment(self, environment_id: str) -> bool:
        if environment_id == self.fail_on:
            raise RuntimeError("boom")
        if environment_id in self.registered:
            return False
        self.registered.append(environment_id)
        return True


class _ListingService:
    def list_environment_ids(self) -> list[str]:
        return ["env-a", "env-b", "env-c"]


def test_restart_restores_persisted_environments_into_dispatcher() -> None:
    """Regression: pending orders of pre-restart environments were never executed."""
    from crypto_lab.api.app import register_existing_environments

    dispatcher = _FakeDispatcher()
    assert register_existing_environments(dispatcher, _ListingService()) == [
        "env-a",
        "env-b",
        "env-c",
    ]
    # Idempotent: a second pass registers nothing new.
    assert register_existing_environments(dispatcher, _ListingService()) == []


def test_one_broken_environment_does_not_block_the_others() -> None:
    from crypto_lab.api.app import register_existing_environments

    dispatcher = _FakeDispatcher(fail_on="env-b")
    assert register_existing_environments(dispatcher, _ListingService()) == ["env-a", "env-c"]
