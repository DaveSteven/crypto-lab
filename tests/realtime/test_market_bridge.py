import asyncio
from decimal import Decimal

from crypto_lab.market_data import OrderBookView
from crypto_lab.models import (
    Candle,
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    MarketEventEnvelope,
    PriceLevel,
    TransportType,
)
from crypto_lab.realtime import MarketRealtimeBridge, RealtimeHubRegistry, Subscription


def candle_event(event_id: str, open_ts_ms: int, *, closed: bool):
    return MarketEventEnvelope[Candle](
        event_id=event_id,
        event_type="CANDLE",
        exchange_id=ExchangeId.OKX,
        instrument_id="okx:SPOT:BTC/USDT",
        source_type=DataSourceType.LIVE,
        transport=TransportType.WEBSOCKET,
        exchange_ts_ms=open_ts_ms,
        received_ts_ms=open_ts_ms + 1,
        quality_status=DataQualityStatus.VALID,
        payload=Candle(
            interval="1m",
            open_ts_ms=open_ts_ms,
            close_ts_ms=open_ts_ms + 60_000,
            open="100",
            high="102",
            low="99",
            close="101",
            is_closed=closed,
        ),
    )


def test_unclosed_candles_coalesce_only_same_interval_and_open_time() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        hub = registry.hub("env-1")
        connection = hub.connect()
        hub.subscribe(connection, {Subscription(name="market.candle")})
        bridge = MarketRealtimeBridge(registry)
        await bridge.publish_canonical("env-1", candle_event("one", 60_000, closed=False))
        await bridge.publish_canonical("env-1", candle_event("update", 60_000, closed=False))
        await bridge.publish_canonical("env-1", candle_event("next", 120_000, closed=False))
        assert [item.event_id for item in connection.buffer.snapshot()] == ["update", "next"]

    asyncio.run(scenario())


def test_closed_candle_is_not_silently_coalesced() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        hub = registry.hub("env-1")
        connection = hub.connect()
        hub.subscribe(connection, {Subscription(name="market.candle")})
        bridge = MarketRealtimeBridge(registry)
        await bridge.publish_canonical("env-1", candle_event("open", 60_000, closed=False))
        await bridge.publish_canonical("env-1", candle_event("closed", 60_000, closed=True))
        assert [item.event_id for item in connection.buffer.snapshot()] == ["open", "closed"]

    asyncio.run(scenario())


def test_invalid_order_book_publishes_quality_not_stale_snapshot() -> None:
    async def scenario():
        registry = RealtimeHubRegistry()
        hub = registry.hub("env-1")
        connection = hub.connect()
        hub.subscribe(
            connection,
            {Subscription(name="market.order_book"), Subscription(name="market.quality")},
        )
        bridge = MarketRealtimeBridge(registry)
        view = OrderBookView(
            exchange_id=ExchangeId.OKX,
            instrument_id="okx:SPOT:BTC/USDT",
            bids=(PriceLevel(price=Decimal("99"), quantity=Decimal("1")),),
            asks=(PriceLevel(price=Decimal("101"), quantity=Decimal("1")),),
            depth=1,
            sequence_id="1",
            source_event_id="book-1",
            exchange_ts_ms=1_000,
            received_ts_ms=1_000,
            quality_status=DataQualityStatus.VALID,
            synchronized=True,
            source_connected=True,
        )
        await bridge.publish_order_book_view("env-1", view, now_ms=4_000)
        queued = connection.buffer.snapshot()
        assert len(queued) == 1
        assert queued[0].type == "market.quality"
        assert queued[0].payload["quality_status"] == "STALE"

    asyncio.run(scenario())
