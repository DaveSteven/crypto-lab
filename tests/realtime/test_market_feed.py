import asyncio
import json
from decimal import Decimal

from crypto_lab.realtime import (
    MarketRealtimeBridge,
    OkxMarketFeed,
    RealtimeHubRegistry,
    Subscription,
)

INSTRUMENT = "okx:SPOT:BTC/USDT"

TICKER_MESSAGE = json.dumps(
    {
        "arg": {"channel": "tickers", "instId": "BTC-USDT"},
        "data": [
            {
                "instId": "BTC-USDT",
                "last": "101",
                "askPx": "101.1",
                "askSz": "2",
                "bidPx": "100.9",
                "bidSz": "3",
                "open24h": "99",
                "high24h": "103",
                "low24h": "98",
                "vol24h": "1000",
                "volCcy24h": "100000",
                "ts": "1000",
            }
        ],
    }
)

TRADE_MESSAGE = json.dumps(
    {
        "arg": {"channel": "trades", "instId": "BTC-USDT"},
        "data": [
            {
                "instId": "BTC-USDT",
                "tradeId": "t1",
                "px": "101",
                "sz": "0.5",
                "side": "buy",
                "ts": "1000",
            }
        ],
    }
)

CANDLE_MESSAGE = json.dumps(
    {
        "arg": {"channel": "candle1m", "instId": "BTC-USDT"},
        "data": [["60000", "100", "102", "99", "101", "5", "500", "500", "0"]],
    }
)

BOOK_SNAPSHOT_MESSAGE = json.dumps(
    {
        "arg": {"channel": "books", "instId": "BTC-USDT"},
        "action": "snapshot",
        "data": [{"seqId": 10, "ts": "1000", "bids": [["100", "1"]], "asks": [["101", "1"]]}],
    }
)

BOOK_UPDATE_MESSAGE = json.dumps(
    {
        "arg": {"channel": "books", "instId": "BTC-USDT"},
        "action": "update",
        "data": [
            {
                "seqId": 11,
                "prevSeqId": 10,
                "ts": "1001",
                "bids": [["100.5", "2"]],
                "asks": [["102", "1"]],
            }
        ],
    }
)

BOOK_GAP_MESSAGE = json.dumps(
    {
        "arg": {"channel": "books", "instId": "BTC-USDT"},
        "action": "update",
        "data": [
            {
                "seqId": 99,
                "prevSeqId": 999,
                "ts": "1002",
                "bids": [["100", "1"]],
                "asks": [["101", "1"]],
            }
        ],
    }
)


class FakeConnection:
    def __init__(self, *messages: str) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._messages = iter(messages)

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def recv(self) -> str:
        try:
            return next(self._messages)
        except StopIteration as exc:
            raise ConnectionError("connection closed") from exc

    async def close(self) -> None:
        self.closed = True


class ManualClock:
    def __init__(self) -> None:
        self.now = 1_000

    def advance(self, milliseconds: int) -> None:
        self.now += milliseconds

    def __call__(self) -> int:
        return self.now


class ConnectionScript:
    def __init__(self, *connections: FakeConnection) -> None:
        self.connections = list(connections)
        self.urls: list[str] = []

    async def __call__(self, url: str):
        self.urls.append(url)
        if not self.connections:
            raise OSError("no more scripted connections")
        return self.connections.pop(0)


def make_feed(registry, clock, script, *, channels=("ticker", "trade", "order_book")):
    bridge = MarketRealtimeBridge(registry)
    return OkxMarketFeed(
        bridge,
        environment_id="env-1",
        instruments=(INSTRUMENT,),
        channels=channels,
        candle_interval="1m",
        connection_factory=script,
        now_ms=clock,
        ping_interval_seconds=10.0,
        stale_after_ms=5_000,
        reconnect_delays_seconds=(0.0, 0.0, 0.0, 0.0),
    )


def subscribe_all(hub):
    connection = hub.connect()
    hub.subscribe(
        connection,
        {
            Subscription(name="market.ticker"),
            Subscription(name="market.trade"),
            Subscription(name="market.candle"),
            Subscription(name="market.order_book"),
            Subscription(name="market.quality"),
        },
    )
    return connection


def test_feed_subscribes_all_configured_channels_and_pumps_events() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        hub = registry.hub("env-1")
        client = subscribe_all(hub)
        clock = ManualClock()
        public = FakeConnection("pong", TICKER_MESSAGE, TRADE_MESSAGE)
        business = FakeConnection(CANDLE_MESSAGE)
        script = ConnectionScript(public, business)
        feed = make_feed(
            registry, clock, script, channels=("ticker", "trade", "candle", "order_book")
        )
        run_task = asyncio.create_task(feed.run())
        while len(client.buffer.snapshot()) < 3:
            await asyncio.sleep(0)
            if run_task.done():
                break
        await feed.stop()
        await asyncio.wait_for(run_task, timeout=1)
        # Candles ride the OKX business endpoint; the rest use the public one.
        public_request = json.loads(public.sent[0])
        assert public_request["op"] == "subscribe"
        assert {
            argument["channel"] for argument in public_request["args"]
        } == {"tickers", "trades", "books"}
        business_request = json.loads(business.sent[0])
        assert {
            argument["channel"] for argument in business_request["args"]
        } == {"candle1m"}
        topics = [event.type for event in client.buffer.snapshot()]
        # A quality event may follow once the scripted connections run dry;
        # the first three deliveries must be the canonical market events.
        assert topics[:3] == ["market.ticker", "market.trade", "market.candle"]
        assert "market.order_book" not in topics[:3]

    asyncio.run(scenario())


def test_order_book_snapshot_and_delta_publish_merged_view() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        hub = registry.hub("env-1")
        client = subscribe_all(hub)
        clock = ManualClock()
        script = ConnectionScript(
            FakeConnection(BOOK_SNAPSHOT_MESSAGE, BOOK_UPDATE_MESSAGE)
        )
        feed = make_feed(registry, clock, script)
        run_task = asyncio.create_task(feed.run())
        while feed.stats["messages_received"] < 2:
            await asyncio.sleep(0)
            if run_task.done():
                break
        await feed.stop()
        await asyncio.wait_for(run_task, timeout=1)
        books = [event for event in client.buffer.snapshot() if event.type == "market.order_book"]
        # Ticker/OrderBook state is coalescible, so only the newest view must remain.
        assert len(books) == 1
        merged = books[-1].payload
        bid_prices = [Decimal(level["price"]) for level in merged["bids"]]
        ask_prices = [Decimal(level["price"]) for level in merged["asks"]]
        assert bid_prices == [Decimal("100.5"), Decimal("100")]
        assert ask_prices == [Decimal("101"), Decimal("102")]
        assert merged["sequence_id"] == "11"

    asyncio.run(scenario())


def test_order_book_sequence_gap_publishes_quality_and_resubscribes() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        hub = registry.hub("env-1")
        client = subscribe_all(hub)
        clock = ManualClock()
        connection = FakeConnection(BOOK_SNAPSHOT_MESSAGE, BOOK_GAP_MESSAGE)
        script = ConnectionScript(connection)
        feed = make_feed(registry, clock, script)
        run_task = asyncio.create_task(feed.run())
        while not any(
            event.payload.get("quality_status") == "UNSYNCED"
            for event in client.buffer.snapshot()
        ):
            await asyncio.sleep(0)
            if run_task.done():
                break
        await feed.stop()
        await asyncio.wait_for(run_task, timeout=1)
        operations = [json.loads(text) for text in connection.sent]
        assert any(operation.get("op") == "unsubscribe" for operation in operations)
        assert any(operation.get("op") == "subscribe" for operation in operations)
        assert feed.stats["resynchronizations"] == 1
        quality_events = [
            event for event in client.buffer.snapshot() if event.type == "market.quality"
        ]
        statuses = [event.payload["quality_status"] for event in quality_events]
        assert "UNSYNCED" in statuses
        assert statuses.count("UNSYNCED") == 1

    asyncio.run(scenario())


def test_repeated_invalid_books_do_not_resubscribe_repeatedly() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        hub = registry.hub("env-1")
        subscribe_all(hub)
        clock = ManualClock()
        connection = FakeConnection(
            BOOK_SNAPSHOT_MESSAGE, BOOK_GAP_MESSAGE, BOOK_GAP_MESSAGE
        )
        script = ConnectionScript(connection)
        feed = make_feed(registry, clock, script)
        run_task = asyncio.create_task(feed.run())
        while feed.stats["messages_received"] < 3:
            await asyncio.sleep(0)
            if run_task.done():
                break
        await feed.stop()
        await asyncio.wait_for(run_task, timeout=1)
        operations = [json.loads(text) for text in connection.sent]
        unsubscribes = [
            operation for operation in operations if operation.get("op") == "unsubscribe"
        ]
        assert len(unsubscribes) == 1

    asyncio.run(scenario())


def test_connection_loss_marks_stale_then_reconnects_and_resubscribes() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        hub = registry.hub("env-1")
        client = subscribe_all(hub)
        clock = ManualClock()
        broken = FakeConnection(TICKER_MESSAGE)
        healthy = FakeConnection(TICKER_MESSAGE)
        script = ConnectionScript(broken, healthy)
        feed = make_feed(registry, clock, script)
        run_task = asyncio.create_task(feed.run())
        while feed.stats["reconnects"] < 1 or not healthy.sent:
            await asyncio.sleep(0)
            if run_task.done():
                break
        await feed.stop()
        await asyncio.wait_for(run_task, timeout=1)
        assert feed.stats["reconnects"] >= 1
        quality_events = [
            event for event in client.buffer.snapshot() if event.type == "market.quality"
        ]
        assert any(
            event.payload["quality_status"] == "STALE" for event in quality_events
        )
        second_subscribe = json.loads(healthy.sent[0])
        assert second_subscribe["op"] == "subscribe"
        channels = {argument["channel"] for argument in second_subscribe["args"]}
        assert channels == {"tickers", "trades", "books"}

    asyncio.run(scenario())


def test_stale_data_publishes_quality_once_then_recovers() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        hub = registry.hub("env-1")
        client = subscribe_all(hub)
        clock = ManualClock()

        class DelayedConnection(FakeConnection):
            async def recv(self) -> str:
                clock.advance(6_000)
                return await super().recv()

        connection = DelayedConnection(TICKER_MESSAGE, TICKER_MESSAGE)
        script = ConnectionScript(connection)
        feed = make_feed(registry, clock, script)
        run_task = asyncio.create_task(feed.run())
        while feed.stats["stale_transitions"] < 1:
            await asyncio.sleep(0)
            if run_task.done():
                break
        await feed.stop()
        await asyncio.wait_for(run_task, timeout=1)
        quality_events = [
            event for event in client.buffer.snapshot() if event.type == "market.quality"
        ]
        statuses = [event.payload["quality_status"] for event in quality_events]
        assert statuses.count("STALE") == 1

    asyncio.run(scenario())


def test_invalid_instrument_and_malformed_messages_are_counted_not_published() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        hub = registry.hub("env-1")
        client = subscribe_all(hub)
        clock = ManualClock()
        connection = FakeConnection(
            "not-json",
            json.dumps({"arg": {"channel": "tickers", "instId": "ETH-USDT"}, "data": []}),
            TICKER_MESSAGE,
        )
        script = ConnectionScript(connection)
        feed = make_feed(registry, clock, script)
        run_task = asyncio.create_task(feed.run())
        while len(client.buffer.snapshot()) < 1:
            await asyncio.sleep(0)
            if run_task.done():
                break
        await feed.stop()
        await asyncio.wait_for(run_task, timeout=1)
        assert feed.stats["invalid_messages"] == 2
        topics = [event.type for event in client.buffer.snapshot()]
        assert "market.ticker" in topics
        instruments = {
            event.instrument_id
            for event in client.buffer.snapshot()
            if event.instrument_id is not None
        }
        assert instruments == {INSTRUMENT}

    asyncio.run(scenario())


def test_stop_closes_connection_and_run_returns() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        subscribe_all(registry.hub("env-1"))
        clock = ManualClock()

        class HangingConnection(FakeConnection):
            def __init__(self) -> None:
                super().__init__()
                self.closed = False

            async def recv(self) -> str:
                while not self.closed:
                    await asyncio.sleep(0.01)
                raise ConnectionError("connection closed")

        connection = HangingConnection()
        script = ConnectionScript(connection)
        feed = make_feed(registry, clock, script)
        run_task = asyncio.create_task(feed.run())
        while not connection.sent:
            await asyncio.sleep(0)
            if run_task.done():
                break
        await feed.stop()
        await asyncio.wait_for(run_task, timeout=1)
        assert connection.closed is True

    asyncio.run(scenario())
