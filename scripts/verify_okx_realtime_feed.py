#!/usr/bin/env python3
"""Bounded real-interface validation of the OKX public market feed.

Subscribes to the configured channels on the OKX public WebSocket for a
fixed duration, records per-channel message counts, canonical event counts
and quality transitions, and writes a structured JSON report.

Usage:
    .venv/bin/python scripts/verify_okx_realtime_feed.py --duration 15
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crypto_lab.market_data import OrderBookView  # noqa: E402
from crypto_lab.models import MarketEventEnvelope  # noqa: E402
from crypto_lab.realtime import OKX_PUBLIC_WS_URL, OkxMarketFeed  # noqa: E402
from crypto_lab.realtime.market import MarketRealtimeBridge  # noqa: E402

INSTRUMENT = "okx:SPOT:BTC/USDT"


class ValidationRecorder:
    def __init__(self) -> None:
        self.canonical_by_type: Counter[str] = Counter()
        self.canonical_instruments: set[str] = set()
        self.order_book_views = 0
        self.quality_by_status: Counter[str] = Counter()
        self.first_event_ts_ms: int | None = None
        self.last_event_ts_ms: int | None = None
        self.latest_ticker: dict[str, Any] | None = None
        self.latest_book: dict[str, Any] | None = None
        self.closed_candles = 0
        self.unclosed_candles = 0
        self.trade_sides: Counter[str] = Counter()

    async def on_canonical(self, event: MarketEventEnvelope) -> None:
        self.canonical_by_type[event.event_type] += 1
        self.canonical_instruments.add(event.instrument_id)
        received = event.received_ts_ms
        self.first_event_ts_ms = (
            received if self.first_event_ts_ms is None else min(self.first_event_ts_ms, received)
        )
        self.last_event_ts_ms = (
            received if self.last_event_ts_ms is None else max(self.last_event_ts_ms, received)
        )
        if event.event_type == "TICKER":
            self.latest_ticker = {
                "bid": str(event.payload.bid),
                "ask": str(event.payload.ask),
                "last": str(event.payload.last),
                "exchange_ts_ms": event.exchange_ts_ms,
                "quality": event.quality_status.value,
            }
        elif event.event_type == "TRADE":
            self.trade_sides[event.payload.side.value] += 1
        elif event.event_type == "CANDLE":
            if event.payload.is_closed:
                self.closed_candles += 1
            else:
                self.unclosed_candles += 1

    async def on_order_book_view(self, view: OrderBookView) -> None:
        self.order_book_views += 1
        self.latest_book = {
            "sequence_id": view.sequence_id,
            "best_bid": str(view.bids[0].price) if view.bids else None,
            "best_ask": str(view.asks[0].price) if view.asks else None,
            "received_ts_ms": view.received_ts_ms,
        }


class CountingBridge(MarketRealtimeBridge):
    def __init__(self, registry) -> None:  # type: ignore[no-untyped-def]
        super().__init__(registry)
        self.published_by_topic: Counter[str] = Counter()

    async def publish_canonical(self, environment_id, event):  # type: ignore[no-untyped-def]
        self.published_by_topic[f"hub:{event.event_type}"] += 1
        return await super().publish_canonical(environment_id, event)


def build_report(
    recorder: ValidationRecorder,
    bridge: CountingBridge,
    feed: OkxMarketFeed,
    *,
    duration_seconds: int,
    started_ts: str,
) -> dict[str, Any]:
    return {
        "verification": "okx_public_websocket_feed",
        "data_source": "OKX public WebSocket (wss://ws.okx.com:8443/ws/v5/public)",
        "channels": ["tickers", "trades", f"candle{feed.candle_interval}", "books"],
        "instrument": INSTRUMENT,
        "duration_seconds": duration_seconds,
        "started_at_utc": started_ts,
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "subscription": {
            "messages_received": feed.stats["messages_received"],
            "subscription_errors": feed.stats["subscription_errors"],
            "reconnects": feed.stats["reconnects"],
            "resynchronizations": feed.stats["resynchronizations"],
            "stale_transitions": feed.stats["stale_transitions"],
        },
        "canonical_events": {
            "by_type": dict(recorder.canonical_by_type),
            "instruments": sorted(recorder.canonical_instruments),
            "first_received_ts_ms": recorder.first_event_ts_ms,
            "last_received_ts_ms": recorder.last_event_ts_ms,
            "trade_sides": dict(recorder.trade_sides),
            "closed_candles": recorder.closed_candles,
            "unclosed_candles": recorder.unclosed_candles,
        },
        "order_book_views": recorder.order_book_views,
        "latest_ticker": recorder.latest_ticker,
        "latest_order_book": recorder.latest_book,
        "hub_publication_counts": dict(bridge.published_by_topic),
    }


async def run(duration_seconds: int) -> dict[str, Any]:
    from crypto_lab.realtime.hub import RealtimeHubRegistry

    registry = RealtimeHubRegistry()
    bridge = CountingBridge(registry)
    recorder = ValidationRecorder()
    feed = OkxMarketFeed(
        bridge,
        environment_id="verification",
        instruments=(INSTRUMENT,),
        channels=("ticker", "trade", "candle", "order_book"),
        url=OKX_PUBLIC_WS_URL,
        reconnect_delays_seconds=(1.0, 2.0, 5.0, 10.0),
        on_canonical=recorder.on_canonical,
        on_order_book_view=recorder.on_order_book_view,
    )
    task = asyncio.create_task(feed.run())
    await asyncio.sleep(duration_seconds)
    await feed.stop()
    with_suppress = asyncio.TimeoutError
    try:
        await asyncio.wait_for(task, timeout=5)
    except with_suppress:
        task.cancel()
    return build_report(
        recorder,
        bridge,
        feed,
        duration_seconds=duration_seconds,
        started_ts=datetime.now(UTC).isoformat(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=15)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/okx_realtime_feed_verification.json"),
    )
    arguments = parser.parse_args()

    report = asyncio.run(run(arguments.duration))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    canonical = report["canonical_events"]
    print(json.dumps(report["subscription"], indent=2))
    print("canonical events:", json.dumps(canonical["by_type"]))
    print("order book views:", report["order_book_views"])
    print("latest ticker:", json.dumps(report["latest_ticker"]))
    print("latest order book:", json.dumps(report["latest_order_book"]))
    print(f"report written to {arguments.output}")


if __name__ == "__main__":
    started = time.time()
    main()
    print(f"wall clock: {time.time() - started:.1f}s")
