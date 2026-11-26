"""Adapters from validated Canonical Market Data to frontend realtime topics."""

from __future__ import annotations

from typing import Any

from crypto_lab.market_data import OrderBookView
from crypto_lab.models import (
    Candle,
    DataQualityStatus,
    MarketEventEnvelope,
    OrderBookSnapshot,
    Ticker,
    Trade,
)
from crypto_lab.realtime.hub import RealtimeEvent, RealtimeHubRegistry


class MarketRealtimeBridge:
    def __init__(self, registry: RealtimeHubRegistry) -> None:
        self.registry = registry

    async def publish_canonical(
        self,
        environment_id: str,
        event: MarketEventEnvelope[Any],
    ) -> None:
        if event.quality_status is not DataQualityStatus.VALID:
            await self.publish_quality(
                environment_id,
                instrument_id=event.instrument_id,
                event_id=f"{event.event_id}:quality",
                event_ts_ms=event.received_ts_ms,
                quality_status=event.quality_status,
                reason="canonical event is not valid",
            )
            return
        payload = event.payload.model_dump(mode="json")
        if isinstance(event.payload, Ticker):
            topic, coalescible = "market.ticker", True
            interval = None
            candle_open_ts_ms = None
            candle_closed = None
        elif isinstance(event.payload, Trade):
            topic, coalescible = "market.trade", False
            interval = None
            candle_open_ts_ms = None
            candle_closed = None
        elif isinstance(event.payload, Candle):
            topic = "market.candle"
            coalescible = not event.payload.is_closed
            interval = event.payload.interval
            candle_open_ts_ms = event.payload.open_ts_ms
            candle_closed = event.payload.is_closed
        elif isinstance(event.payload, OrderBookSnapshot):
            topic, coalescible = "market.order_book", True
            interval = None
            candle_open_ts_ms = None
            candle_closed = None
        else:
            raise TypeError("unsupported Canonical payload for realtime publication")
        await self.registry.publish(
            environment_id,
            RealtimeEvent(
                topic=topic,
                event_id=event.event_id,
                event_ts_ms=event.exchange_ts_ms or event.received_ts_ms,
                payload=payload,
                instrument_id=event.instrument_id,
                interval=interval,
                candle_open_ts_ms=candle_open_ts_ms,
                candle_closed=candle_closed,
                coalescible=coalescible,
            ),
        )

    async def publish_order_book_view(
        self,
        environment_id: str,
        view: OrderBookView,
        *,
        now_ms: int,
        stale_after_ms: int = 2_000,
    ) -> None:
        valid = (
            view.quality_status is DataQualityStatus.VALID
            and view.synchronized
            and view.source_connected
            and bool(view.bids and view.asks)
            and view.received_ts_ms <= now_ms
            and now_ms - view.received_ts_ms <= stale_after_ms
        )
        if not valid:
            await self.publish_quality(
                environment_id,
                instrument_id=view.instrument_id,
                event_id=f"{view.source_event_id}:invalid",
                event_ts_ms=now_ms,
                quality_status=(
                    view.quality_status
                    if view.quality_status is not DataQualityStatus.VALID
                    else DataQualityStatus.STALE
                ),
                reason="order book is not executable",
            )
            return
        await self.registry.publish(
            environment_id,
            RealtimeEvent(
                topic="market.order_book",
                event_id=view.source_event_id,
                event_ts_ms=view.exchange_ts_ms or view.received_ts_ms,
                instrument_id=view.instrument_id,
                payload={
                    "bids": [level.model_dump(mode="json") for level in view.bids],
                    "asks": [level.model_dump(mode="json") for level in view.asks],
                    "depth": view.depth,
                    "sequence_id": view.sequence_id,
                    "quality_status": view.quality_status.value,
                    "received_ts_ms": view.received_ts_ms,
                },
                coalescible=True,
            ),
        )

    async def publish_quality(
        self,
        environment_id: str,
        *,
        instrument_id: str,
        event_id: str,
        event_ts_ms: int,
        quality_status: DataQualityStatus,
        reason: str,
    ) -> None:
        await self.registry.publish(
            environment_id,
            RealtimeEvent(
                topic="market.quality",
                event_id=event_id,
                event_ts_ms=event_ts_ms,
                instrument_id=instrument_id,
                payload={"quality_status": quality_status.value, "reason": reason},
                coalescible=False,
            ),
        )
