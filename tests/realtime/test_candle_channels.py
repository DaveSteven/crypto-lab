"""ADR 0008: reference-counted dynamic candle channels."""

from __future__ import annotations

import asyncio
import json

import pytest

from crypto_lab.realtime import OkxMarketFeed, RealtimeHubRegistry
from crypto_lab.realtime.feed import OKX_BUSINESS_WS_URL, SubscriptionLimitError
from crypto_lab.realtime.market import MarketRealtimeBridge

INSTRUMENT = "okx:SPOT:BTC/USDT"


class Sink:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def recv(self) -> str:  # pragma: no cover - not used
        await asyncio.sleep(3600)
        return ""

    async def close(self) -> None:
        pass


def make(max_channels: int = 32, grace: float = 0.02):
    feed = OkxMarketFeed(
        MarketRealtimeBridge(RealtimeHubRegistry()),
        environment_id="shared",
        instruments=(INSTRUMENT,),
        channels=("candle",),
        max_candle_channels=max_channels,
        candle_grace_seconds=grace,
    )
    sink = Sink()
    feed._connections[OKX_BUSINESS_WS_URL] = sink
    return feed, sink


def ops(sink: Sink) -> list[tuple[str, str]]:
    return [(m["op"], m["args"][0]["channel"]) for m in sink.sent]


def test_shared_channel_subscribes_once_and_releases_after_grace() -> None:
    async def scenario():
        feed, sink = make()
        await feed.acquire_candle("a", INSTRUMENT, "5m")
        await feed.acquire_candle("b", INSTRUMENT, "5m")
        await feed.acquire_candle("a", INSTRUMENT, "5m")  # idempotent
        assert ops(sink) == [("subscribe", "candle5m")]
        feed.release_candle("a", INSTRUMENT, "5m")
        await asyncio.sleep(0.05)
        assert ops(sink) == [("subscribe", "candle5m")]  # b still holds it
        feed.release_candle("b", INSTRUMENT, "5m")
        await asyncio.sleep(0.05)
        assert ops(sink)[-1] == ("unsubscribe", "candle5m")
        assert feed.active_candle_channel_count() == 1

    asyncio.run(scenario())


def test_resubscribe_within_grace_cancels_release() -> None:
    async def scenario():
        feed, sink = make(grace=0.05)
        await feed.acquire_candle("a", INSTRUMENT, "1h")
        feed.release_candle("a", INSTRUMENT, "1h")
        await feed.acquire_candle("a", INSTRUMENT, "1h")
        await asyncio.sleep(0.1)
        assert ops(sink) == [("subscribe", "candle1H")]
        assert (INSTRUMENT, "1h") in feed._dynamic_owners

    asyncio.run(scenario())


def test_resident_interval_is_never_released() -> None:
    async def scenario():
        feed, sink = make()
        await feed.acquire_candle("a", INSTRUMENT, "1m")
        feed.release_candle("a", INSTRUMENT, "1m")
        feed.release_owner("a")
        await asyncio.sleep(0.05)
        assert sink.sent == []
        assert feed.active_candle_channel_count() == 1

    asyncio.run(scenario())


def test_limit_is_explicit_error_and_counts_resident() -> None:
    async def scenario():
        feed, sink = make(max_channels=2)  # 1 resident + 1 dynamic
        await feed.acquire_candle("a", INSTRUMENT, "5m")
        with pytest.raises(SubscriptionLimitError) as info:
            await feed.acquire_candle("a", INSTRUMENT, "15m")
        assert info.value.code == "SUBSCRIPTION_LIMIT"
        assert len(sink.sent) == 1

    asyncio.run(scenario())


def test_release_owner_on_disconnect_and_no_negative_counts() -> None:
    async def scenario():
        feed, sink = make()
        await feed.acquire_candle("a", INSTRUMENT, "5m")
        await feed.acquire_candle("a", INSTRUMENT, "4h")
        feed.release_owner("a")
        feed.release_owner("a")
        feed.release_candle("zzz", INSTRUMENT, "5m")
        await asyncio.sleep(0.05)
        assert feed.active_candle_channel_count() == 1
        assert [o for o, _ in ops(sink)].count("unsubscribe") == 2

    asyncio.run(scenario())


def test_reconnect_subscription_includes_active_dynamic_channels() -> None:
    async def scenario():
        feed, _ = make()
        await feed.acquire_candle("a", INSTRUMENT, "5m")
        args = feed._subscription_arguments(("candle",))
        assert {a["channel"] for a in args} == {"candle1m", "candle5m"}

    asyncio.run(scenario())


def test_rejects_unknown_instrument_and_interval() -> None:
    async def scenario():
        feed, _ = make()
        with pytest.raises(ValueError):
            await feed.acquire_candle("a", "okx:SPOT:ETH/USDT", "5m")
        with pytest.raises(ValueError):
            await feed.acquire_candle("a", INSTRUMENT, "2m")

    asyncio.run(scenario())
