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
