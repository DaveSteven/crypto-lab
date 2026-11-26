"""OKX public WebSocket feed publishing canonical market events in realtime.

The feed owns the exchange connection lifecycle (subscribe, application-level
keepalive, resubscribe after order-book desynchronization, bounded reconnect
backoff) and hands every validated Canonical event to the MarketRealtimeBridge.
It never fabricates market data: messages that fail validation are counted and
surfaced as quality events, never replaced by synthetic values.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, Protocol

from crypto_lab.market_data import (
    OKX_CHANNEL,
    InvalidOrderBookStateError,
    OrderBookMarketState,
    normalize_okx_order_book,
    normalize_okx_tickers,
    normalize_okx_trades,
    normalize_okx_websocket_candles,
)
from crypto_lab.models import DataQualityStatus, ExchangeId
from crypto_lab.realtime.market import MarketRealtimeBridge

OKX_PUBLIC_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

CHANNEL_REQUEST_NAME = {
    "ticker": "tickers",
    "trade": "trades",
    "order_book": "books",
}

CANDLE_KIND = "candle"


class Connection(Protocol):
    async def send(self, text: str) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


ConnectionFactory = Callable[[str], Awaitable[Connection]]


async def _default_connection(url: str) -> Connection:
    import websockets

    return await websockets.connect(
        url,
        open_timeout=5,
        close_timeout=2,
        # OKX keepalive uses application-level "ping"/"pong" text frames.
        ping_interval=None,
    )


class OkxMarketFeed:
    """Drive one OKX public WebSocket connection into one environment hub."""

    def __init__(
        self,
        bridge: MarketRealtimeBridge,
        *,
        environment_id: str,
        instruments: Iterable[str],
        channels: Iterable[str] = ("ticker", "trade", "order_book"),
        candle_interval: str = "1m",
        url: str = OKX_PUBLIC_WS_URL,
        connection_factory: ConnectionFactory = _default_connection,
        now_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        ping_interval_seconds: float = 20.0,
        stale_after_ms: int = 10_000,
        reconnect_delays_seconds: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0),
        order_book_state: OrderBookMarketState | None = None,
    ) -> None:
        self.bridge = bridge
        self.environment_id = environment_id
        self.instruments = tuple(instruments)
        self.channels = tuple(channels)
        self.candle_interval = candle_interval
        self.url = url
        self.connection_factory = connection_factory
        self.now_ms = now_ms
        self.ping_interval_seconds = ping_interval_seconds
        self.stale_after_ms = stale_after_ms
        self.reconnect_delays_seconds = reconnect_delays_seconds
        self.order_book_state = order_book_state or OrderBookMarketState()
        if not self.instruments:
            raise ValueError("feed requires at least one instrument")
        for channel in self.channels:
            if channel not in CHANNEL_REQUEST_NAME and channel != CANDLE_KIND:
                raise ValueError(f"unsupported feed channel: {channel}")
        self.stats = {
            "messages_received": 0,
            "invalid_messages": 0,
            "subscription_errors": 0,
            "resynchronizations": 0,
            "reconnects": 0,
            "stale_transitions": 0,
        }
        self._stopping = False
        self._connection: Connection | None = None
        self._supervision: asyncio.Task[None] | None = None
        self._backoff_index = 0
        self._last_message_ms: int | None = None
        self._last_data_ms: dict[str, int] = {}
        self._last_quality: dict[str, str] = {}
        self._book_health: dict[str, str] = {}
        self._awaiting_pong = False
        self._acknowledged: set[tuple[Any, Any]] = set()

    async def run(self) -> None:
        while not self._stopping:
            try:
                connection = await self.connection_factory(self.url)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.stats["reconnects"] += 1
                await self._sleep(self._next_backoff())
                continue
            self._backoff_index = 0
            self._awaiting_pong = False
            self._connection = connection
            self._supervision = asyncio.create_task(self._supervise(connection))
            try:
                await self._subscribe(connection)
                await self._receive_loop(connection)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                await self._shutdown_connection(connection)
            if self._stopping:
                break
            self.stats["reconnects"] += 1
            await self._sleep(self._next_backoff())

    async def stop(self) -> None:
        self._stopping = True
        connection = self._connection
        if connection is not None:
            with contextlib.suppress(Exception):
                await connection.close()

    async def _sleep(self, delay_seconds: float) -> None:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        else:
            # Zero delay must still yield so the reconnect loop cannot spin
            # synchronously and block the event loop.
            await asyncio.sleep(0)

    def _next_backoff(self) -> float:
        index = min(self._backoff_index, len(self.reconnect_delays_seconds) - 1)
        self._backoff_index += 1
        return self.reconnect_delays_seconds[index]

    async def _shutdown_connection(self, connection: Connection) -> None:
        if self._supervision is not None:
            self._supervision.cancel()
            self._supervision = None
        self._connection = None
        with contextlib.suppress(Exception):
            await connection.close()
        await self._mark_disconnected()

    async def _mark_disconnected(self) -> None:
        now_ms = self.now_ms()
        for instrument_id in self.instruments:
            self.order_book_state.mark_disconnected(ExchangeId.OKX, instrument_id)
            await self._publish_quality(
                instrument_id,
                DataQualityStatus.STALE,
                "market data connection lost",
                now_ms,
            )

    async def _subscribe(self, connection: Connection) -> None:
        arguments = self._subscription_arguments()
        if not arguments:
            raise ValueError("feed produced no subscription arguments")
        await connection.send(json.dumps({"op": "subscribe", "args": arguments}))

    def _subscription_arguments(self) -> list[dict[str, str]]:
        arguments: list[dict[str, str]] = []
        for instrument_id in self.instruments:
            instrument = _okx_instrument(instrument_id)
            for channel in self.channels:
                if channel == CANDLE_KIND:
                    arguments.append(
                        {
                            "channel": OKX_CHANNEL[self.candle_interval],
                            "instId": instrument,
                        }
                    )
                else:
                    arguments.append(
                        {"channel": CHANNEL_REQUEST_NAME[channel], "instId": instrument}
                    )
        return arguments

    async def _resubscribe_order_book(self, connection: Connection, instrument: str) -> None:
        argument = {"channel": "books", "instId": _okx_instrument(instrument)}
        await connection.send(
            json.dumps({"op": "unsubscribe", "args": [argument]}),
        )
        await connection.send(json.dumps({"op": "subscribe", "args": [argument]}))
        self.stats["resynchronizations"] += 1

    async def _receive_loop(self, connection: Connection) -> None:
        while True:
            message = await connection.recv()
            now_ms = self.now_ms()
            self._last_message_ms = now_ms
            self._awaiting_pong = False
            if message == "pong":
                continue
            self.stats["messages_received"] += 1
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            try:
                payload = json.loads(message)
            except (TypeError, ValueError):
                self.stats["invalid_messages"] += 1
                continue
            if not isinstance(payload, dict):
                self.stats["invalid_messages"] += 1
                continue
            if "event" in payload:
                self._handle_event_message(payload)
                continue
            await self._dispatch_data(payload, now_ms)

    def _handle_event_message(self, payload: Mapping[str, Any]) -> None:
        event = payload.get("event")
        argument = payload.get("arg")
        if event == "error":
            self.stats["subscription_errors"] += 1
            return
        if event in {"subscribe", "unsubscribe"} and isinstance(argument, dict):
            self._acknowledged.add((argument.get("channel"), argument.get("instId")))

    async def _dispatch_data(self, payload: Mapping[str, Any], now_ms: int) -> None:
        argument = payload.get("arg")
        if not isinstance(argument, dict):
            self.stats["invalid_messages"] += 1
            return
        channel = argument.get("channel")
        instrument = argument.get("instId")
        if not isinstance(channel, str) or not isinstance(instrument, str):
            self.stats["invalid_messages"] += 1
            return
        instrument_id = _canonical_instrument(instrument)
        if instrument_id not in self.instruments:
            self.stats["invalid_messages"] += 1
            return
        try:
            if channel == "tickers":
                await self._publish_canonical(
                    normalize_okx_tickers(payload, received_ts_ms=now_ms),
                    now_ms,
                )
            elif channel == "trades":
                for event in normalize_okx_trades(payload, received_ts_ms=now_ms):
                    await self._publish_canonical(event, now_ms)
            elif channel == "books":
                await self._apply_order_book(payload, now_ms)
            elif channel in OKX_CHANNEL.values():
                for event in normalize_okx_websocket_candles(payload, received_ts_ms=now_ms):
                    if (
                        event.payload.interval == self.candle_interval
                        and event.instrument_id in self.instruments
                    ):
                        await self._publish_canonical(event, now_ms)
            else:
                self.stats["invalid_messages"] += 1
        except (TypeError, ValueError):
            self.stats["invalid_messages"] += 1

    async def _apply_order_book(self, payload: Mapping[str, Any], now_ms: int) -> None:
        event = normalize_okx_order_book(payload, received_ts_ms=now_ms)
        previous_health = self._book_health.get(event.instrument_id, "healthy")
        try:
            if event.event_type == "ORDER_BOOK_SNAPSHOT":
                view = self.order_book_state.apply_snapshot(event)
            else:
                view = self.order_book_state.apply_delta(event)
        except InvalidOrderBookStateError:
            self._book_health[event.instrument_id] = "unsynced"
            if previous_health != "unsynced":
                await self.bridge.publish_quality(
                    self.environment_id,
                    instrument_id=event.instrument_id,
                    event_id=f"{event.event_id}:unsynced",
                    event_ts_ms=now_ms,
                    quality_status=DataQualityStatus.UNSYNCED,
                    reason="order-book sequence gap detected",
                )
                connection = self._connection
                if connection is not None:
                    await self._resubscribe_order_book(connection, event.instrument_id)
            return
        healthy = view.quality_status is DataQualityStatus.VALID and view.synchronized
        health = "healthy" if healthy else "invalid"
        if not healthy and previous_health == health:
            return
        self._book_health[event.instrument_id] = health
        self._record_data(event.instrument_id, now_ms)
        await self.bridge.publish_order_book_view(
            self.environment_id, view, now_ms=now_ms, stale_after_ms=self.stale_after_ms
        )

    async def _publish_canonical(self, event: Any, now_ms: int) -> None:
        valid = event.quality_status is DataQualityStatus.VALID
        previous = self._last_quality.get(event.instrument_id)
        if not valid and previous == event.quality_status.value:
            return
        self._last_quality[event.instrument_id] = event.quality_status.value
        self._record_data(event.instrument_id, now_ms)
        if previous == DataQualityStatus.STALE.value and valid:
            await self.bridge.publish_quality(
                self.environment_id,
                instrument_id=event.instrument_id,
                event_id=f"{event.event_id}:recovered",
                event_ts_ms=now_ms,
                quality_status=DataQualityStatus.VALID,
                reason="market data resumed",
            )
        await self.bridge.publish_canonical(self.environment_id, event)

    def _record_data(self, instrument_id: str, now_ms: int) -> None:
        self._last_data_ms[instrument_id] = now_ms

    async def _publish_quality(
        self,
        instrument_id: str,
        quality_status: DataQualityStatus,
        reason: str,
        now_ms: int,
    ) -> None:
        if self._last_quality.get(instrument_id) == quality_status.value:
            return
        self._last_quality[instrument_id] = quality_status.value
        if quality_status is DataQualityStatus.STALE:
            self.stats["stale_transitions"] += 1
        await self.bridge.publish_quality(
            self.environment_id,
            instrument_id=instrument_id,
            event_id=f"okx:{instrument_id}:quality:{quality_status.value}:{now_ms}",
            event_ts_ms=now_ms,
            quality_status=quality_status,
            reason=reason,
        )

    async def _supervise(self, connection: Connection) -> None:
        try:
            while True:
                await asyncio.sleep(self.ping_interval_seconds)
                now_ms = self.now_ms()
                if self._awaiting_pong:
                    raise ConnectionError("OKX keepalive pong was not received")
                self._awaiting_pong = True
                await connection.send("ping")
                await self._check_staleness(now_ms)
        except asyncio.CancelledError:
            return
        except Exception:
            # Force a reconnect by closing the receive loop's connection.
            with contextlib.suppress(Exception):
                await connection.close()

    async def _check_staleness(self, now_ms: int) -> None:
        for instrument_id in self.instruments:
            last = self._last_data_ms.get(instrument_id)
            if last is not None and now_ms - last > self.stale_after_ms:
                await self._publish_quality(
                    instrument_id,
                    DataQualityStatus.STALE,
                    "market data is stale",
                    now_ms,
                )


def _okx_instrument(instrument_id: str) -> str:
    if not instrument_id.startswith("okx:SPOT:"):
        raise ValueError("only OKX SPOT instruments are supported")
    symbol = instrument_id.removeprefix("okx:SPOT:")
    if "/" not in symbol:
        raise ValueError("invalid canonical instrument")
    return symbol.replace("/", "-")


def _canonical_instrument(instrument: str) -> str:
    parts = instrument.split("-")
    if len(parts) != 2 or not all(parts):
        raise ValueError("OKX SPOT instrument must contain base and quote currencies")
    return f"okx:SPOT:{parts[0]}/{parts[1]}"
