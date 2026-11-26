import asyncio

from crypto_lab.realtime import RealtimeEvent, RealtimeHubRegistry, RealtimePublisher


def sample_event():
    return RealtimeEvent(
        topic="orders",
        event_id="order-event",
        event_ts_ms=1_000,
        payload={},
        account_id="account-1",
    )


def test_publisher_is_nonblocking_and_observes_async_delivery() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        publisher = RealtimePublisher(registry)
        publisher.start(asyncio.get_running_loop())
        publisher.publish_committed("env-1", (sample_event(),))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert registry.hub("env-1").stream_sequence == 1
        assert publisher.publish_failures == 0

    asyncio.run(scenario())


def test_unavailable_publisher_records_resync_relevant_failure() -> None:
    publisher = RealtimePublisher(RealtimeHubRegistry())
    publisher.publish_committed("env-1", (sample_event(),))
    assert publisher.unavailable_publishes == 1
