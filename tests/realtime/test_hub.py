import asyncio

import pytest

from crypto_lab.realtime import (
    EnvironmentEventHub,
    RealtimeConfig,
    RealtimeEvent,
    ReplayUnavailable,
    Subscription,
)
from crypto_lab.trading import ManualClock


def run(coroutine):
    return asyncio.run(coroutine)


def event(number: int, *, topic="market.ticker", account_id=None, coalescible=True):
    return RealtimeEvent(
        topic=topic,
        event_id=f"event-{number}",
        event_ts_ms=1_000 + number,
        payload={"price": str(number)},
        instrument_id="okx:SPOT:BTC/USDT",
        account_id=account_id,
        coalescible=coalescible,
    )


def test_filtering_gaps_do_not_break_continuous_delivery_sequence() -> None:
    async def scenario():
        hub = EnvironmentEventHub(
            "env-1", config=RealtimeConfig(), clock=ManualClock(1_000), stream_id="stream-1"
        )
        connection = hub.connect()
        hub.subscribe(
            connection,
            {Subscription(name="market.ticker", instrument_id="okx:SPOT:BTC/USDT")},
        )
        await hub.publish(event(1))
        await hub.publish(
            RealtimeEvent(
                topic="market.ticker",
                event_id="other",
                event_ts_ms=1_002,
                payload={},
                instrument_id="okx:SPOT:ETH/USDT",
                coalescible=True,
            )
        )
        await hub.publish(event(3))
        queued = connection.buffer.snapshot()
        assert [item.stream_sequence for item in queued] == [3]
        delivered = connection.deliver(await connection.buffer.get())
        assert delivered["delivery_sequence"] == 1
        assert delivered["stream_sequence"] == 3

    run(scenario())


def test_coalescing_keeps_latest_market_state_without_resync() -> None:
    async def scenario():
        hub = EnvironmentEventHub(
            "env-1",
            config=RealtimeConfig(connection_queue_capacity=1),
            clock=ManualClock(1_000),
        )
        connection = hub.connect()
        hub.subscribe(connection, {Subscription(name="market.ticker")})
        await hub.publish(event(1))
        await hub.publish(event(2))
        assert [item.event_id for item in connection.buffer.snapshot()] == ["event-2"]
        assert connection.buffer.coalesced_count == 1
        assert not connection.requires_resync

    run(scenario())


def test_reliable_event_marks_slow_consumer_for_resync() -> None:
    async def scenario():
        hub = EnvironmentEventHub(
            "env-1", config=RealtimeConfig(connection_queue_capacity=1), clock=ManualClock(1_000)
        )
        connection = hub.connect()
        hub.subscribe(connection, {Subscription(name="orders")})
        await hub.publish(event(1, topic="orders", account_id="a", coalescible=False))
        await hub.publish(event(2, topic="orders", account_id="a", coalescible=False))
        assert connection.requires_resync
        assert hub.publish_failures == 1

    run(scenario())


def test_environment_replay_filters_accounts_and_rejects_old_stream() -> None:
    async def scenario():
        clock = ManualClock(1_000)
        hub = EnvironmentEventHub(
            "env-1",
            config=RealtimeConfig(replay_max_events=2),
            clock=clock,
            stream_id="current",
        )
        await hub.publish(event(1, topic="orders", account_id="a", coalescible=False))
        await hub.publish(event(2, topic="orders", account_id="b", coalescible=False))
        await hub.publish(event(3, topic="orders", account_id="a", coalescible=False))
        connection = hub.connect()
        hub.subscribe(connection, {Subscription(name="orders", account_id="a")})
        assert await hub.replay(connection, stream_id="current", after_sequence=1) == 1
        assert [item.event_id for item in connection.buffer.snapshot()] == ["event-3"]
        with pytest.raises(ReplayUnavailable, match="stream_id"):
            await hub.replay(connection, stream_id="old", after_sequence=2)
        with pytest.raises(ReplayUnavailable, match="outside"):
            await hub.replay(connection, stream_id="current", after_sequence=0)

    run(scenario())


def test_replay_age_and_environment_isolation() -> None:
    async def scenario():
        clock = ManualClock(1_000)
        first = EnvironmentEventHub(
            "env-1",
            config=RealtimeConfig(replay_max_age_ms=60_000),
            clock=clock,
            stream_id="one",
        )
        second = EnvironmentEventHub(
            "env-2", config=RealtimeConfig(), clock=clock, stream_id="two"
        )
        await first.publish(event(1))
        await second.publish(event(2))
        assert first.stats()["stream_sequence"] == 1
        assert second.stats()["stream_sequence"] == 1
        clock.advance(60_001)
        await first.publish(event(3))
        assert first.stats()["replay_events"] == 1

    run(scenario())


def test_disconnect_cleans_queue_and_connection() -> None:
    async def scenario():
        hub = EnvironmentEventHub("env-1", config=RealtimeConfig())
        connection = hub.connect()
        await hub.disconnect(connection)
        assert connection.buffer.closed
        assert hub.stats()["connections"] == 0

    run(scenario())
