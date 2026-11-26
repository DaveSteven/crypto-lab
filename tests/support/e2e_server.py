"""TEST-ONLY backend for browser E2E: real app + real pipeline, scripted exchange feed.

The exchange WebSocket is replaced by a scripted connection that speaks the OKX
message format (tickers/books/trades) with deterministic prices. The data is
SYNTHETIC test data: it never runs unless this module is started explicitly, and
the browser E2E evidence it produces is not real-market evidence. Candle history
is disabled (the chart shows its unavailable state) so no external network is used.

Safety (docs/decisions/0009): refuses to start unless the database name contains
"test", so it can never touch the Local Production or Development databases.

Feed control for fault tests: write ``drop`` into the file named by
``CRYPTO_LAB_E2E_FEED_CONTROL`` to cut the connection (feed goes STALE and
reconnects only after the file is cleared).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from crypto_lab.api import create_app
from crypto_lab.api.market_feed import MarketFeedSettings
from crypto_lab.persistence import schema

BASE_PRICES = {"BTC-USDT": 60_000, "ETH-USDT": 1_700}
CONTROL = Path(os.getenv("CRYPTO_LAB_E2E_FEED_CONTROL", "/tmp/crypto-lab-e2e-feed-control"))


def _dropped() -> bool:
    return CONTROL.exists() and CONTROL.read_text().strip() == "drop"


class ScriptedConnection:
    def __init__(self, public: bool) -> None:
        self.public = public
        self._subscribed: list[tuple[str, str]] = []
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._seq = {inst: 1_000 for inst in BASE_PRICES}
        self._snapshotted: set[str] = set()
        self._closed = False
        self._pump: asyncio.Task[None] | None = None

    async def send(self, text: str) -> None:
        if text == "ping":
            await self._queue.put("pong")
            return
        message = json.loads(text)
        if message.get("op") == "subscribe":
            for argument in message["args"]:
                self._subscribed.append((argument["channel"], argument["instId"]))
            if self._pump is None and self.public:
                self._pump = asyncio.create_task(self._produce())

    async def _produce(self) -> None:
        tick = 0
        while not self._closed:
            now = int(time.time() * 1000)
            for channel, inst in tuple(self._subscribed):
                price = BASE_PRICES[inst]
                bid, ask = price - 0.5, price + 0.5
                if channel == "tickers":
                    data = {
                        "instId": inst,
                        "last": str(price),
                        "askPx": str(ask),
                        "askSz": "5",
                        "bidPx": str(bid),
                        "bidSz": "5",
                        "open24h": str(price - 100),
                        "high24h": str(price + 100),
                        "low24h": str(price - 200),
                        "vol24h": "1000",
                        "volCcy24h": "60000000",
                        "ts": str(now),
                    }
                    await self._queue.put(
                        json.dumps({"arg": {"channel": channel, "instId": inst}, "data": [data]})
                    )
                elif channel == "books":
                    seq = self._seq[inst] = self._seq[inst] + 1
                    levels = {
                        "bids": [[str(bid - i), "50"] for i in range(5)],
                        "asks": [[str(ask + i), "50"] for i in range(5)],
                    }
                    if inst not in self._snapshotted:
                        self._snapshotted.add(inst)
                        action, extra = "snapshot", {}
                    else:
                        # Real OKX sends deltas after the snapshot; re-send the top level with a
                        # changing size so the book keeps moving without a new generation.
                        action = "update"
                        levels = {
                            "bids": [[str(bid), str(50 + seq % 7)]],
                            "asks": [[str(ask), str(50 + seq % 5)]],
                        }
                        extra = {"prevSeqId": seq - 1}
                    book = {"seqId": seq, "ts": str(now), **levels, **extra}
                    await self._queue.put(
                        json.dumps(
                            {
                                "arg": {"channel": channel, "instId": inst},
                                "action": action,
                                "data": [book],
                            }
                        )
                    )
            tick += 1
            await asyncio.sleep(1.0)

    async def recv(self) -> str:
        while True:
            if self._closed or _dropped():
                raise ConnectionError("scripted feed dropped or closed")
            try:
                return await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except TimeoutError:
                continue

    async def close(self) -> None:
        self._closed = True


async def scripted_connection(url: str) -> ScriptedConnection:
    if _dropped():
        raise OSError("scripted feed is down")
    return ScriptedConnection(public="/public" in url)


def main() -> None:
    database_url = os.environ["CRYPTO_LAB_DATABASE_URL"]
    database = make_url(database_url).database or ""
    if "test" not in database:
        raise SystemExit(
            f"refusing to run E2E against database {database!r}: name must contain 'test'"
        )
    CONTROL.unlink(missing_ok=True)
    # Start from an empty test database: every environment is re-registered with the
    # dispatcher and updated per book event, so leftovers would only slow the run.
    engine = create_engine(database_url)
    with engine.begin() as connection:
        for table in reversed(schema.metadata.sorted_tables):
            connection.execute(table.delete())
    engine.dispose()
    app = create_app(
        market_feed_settings=MarketFeedSettings(enabled=True, reconnect_enabled=True),
        feed_connection_factory=scripted_connection,
        candle_client_factory=lambda: None,
    )
    print("E2E backend: SYNTHETIC scripted feed, database", database, flush=True)
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("CRYPTO_LAB_API_PORT", "8642")))


if __name__ == "__main__":
    main()
