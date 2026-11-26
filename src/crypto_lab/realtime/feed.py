"""OKX public WebSocket feed publishing canonical market events in realtime.

The feed owns the exchange connection lifecycle (subscribe, application-level
keepalive, resubscribe after order-book desynchronization, bounded reconnect
backoff) and hands every validated Canonical event to the MarketRealtimeBridge.

OKX serves candle channels on its Business WebSocket endpoint while tickers,
trades and books remain on the public endpoint, so the feed maintains one
connection per required endpoint and treats the whole set as one logical
upstream session. It never fabricates market data: messages that fail
validation are counted and surfaced as quality events, never replaced by
synthetic values.
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

OKX_PUBLIC_WS_URL = "wss://ws.okx.com:443/ws/v5/public"
OKX_BUSINESS_WS_URL = "wss://ws.okx.com:443/ws/v5/business"

CHANNEL_REQUEST_NAME = {
    "ticker": "tickers",
    "trade": "trades",
    "order_book": "books",
}

CANDLE_KIND = "candle"


class SubscriptionLimitError(ValueError):
    """Upstream candle channel cap reached (ADR 0008); never silently dropped."""

    code = "SUBSCRIPTION_LIMIT"


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
        # Local system proxies have shown broken WSS CONNECT handling; the
        # feed connects directly to the exchange public endpoints.
        proxy=None,
    )


CanonicalConsumer = Callable[[Any], Awaitable[None]]
OrderBookConsumer = Callable[[Any], Awaitable[None]]


class OkxMarketFeed:
    """Drive OKX public/business WebSocket connections into the realtime hub."""

    def __init__(
        self,
        bridge: MarketRealtimeBridge,
        *,
        environment_id: str,
        instruments: Iterable[str],
        channels: Iterable[str] = ("ticker", "trade", "order_book"),
        candle_interval: str = "1m",
        candle_intervals: tuple[str, ...] | None = None,
        url: str = OKX_PUBLIC_WS_URL,
        business_url: str = OKX_BUSINESS_WS_URL,
        connection_factory: ConnectionFactory = _default_connection,
        now_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        ping_interval_seconds: float = 20.0,
        stale_after_ms: int = 10_000,
        reconnect_delays_seconds: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0),
        order_book_state: OrderBookMarketState | None = None,
        on_canonical: CanonicalConsumer | None = None,
        on_order_book_view: OrderBookConsumer | None = None,
        max_candle_channels: int = 32,
        candle_grace_seconds: float = 30.0,
    ) -> None:
        self.bridge = bridge
        self.max_candle_channels = max_candle_channels
        self.candle_grace_seconds = candle_grace_seconds
        self.environment_id = environment_id
        self.instruments = tuple(instruments)
        self.channels = tuple(channels)
        self.candle_interval = candle_interval
        # OKX serves candles on the Business endpoint; multiple intervals ride
        # the same business connection so the frontend can switch periods live.
        self.candle_intervals = (
            tuple(candle_intervals) if candle_intervals else (candle_interval,)
        )
        self.url = url
        self.business_url = business_url
        self.connection_factory = connection_factory
        self.now_ms = now_ms
        self.ping_interval_seconds = ping_interval_seconds
        self.stale_after_ms = stale_after_ms
        self.reconnect_delays_seconds = reconnect_delays_seconds
        self.order_book_state = order_book_state or OrderBookMarketState()
        self.on_canonical = on_canonical
        self.on_order_book_view = on_order_book_view
        if not self.instruments:
            raise ValueError("feed requires at least one instrument")
        for instrument_id in self.instruments:
            _okx_instrument(instrument_id)
        for interval in self.candle_intervals:
            if interval not in OKX_CHANNEL:
                raise ValueError(f"unsupported candle interval: {interval}")
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
        self._connections: dict[str, Connection] = {}
        self._supervision: asyncio.Task[None] | None = None
        self._backoff_index = 0
        self._last_message_ms: int | None = None
        self._last_data_ms: dict[str, int] = {}
        self._last_quality: dict[str, str] = {}
        self._book_health: dict[str, str] = {}
        self._awaiting_pong: dict[str, bool] = {}
        self._acknowledged: set[tuple[Any, Any]] = set()
        # ADR 0008: dynamic candle channels keyed by (instrument_id, interval),
        # reference-counted by owner (one owner per client connection).
        self._dynamic_owners: dict[tuple[str, str], set[str]] = {}
        self._grace_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}

    def _endpoint_plan(self) -> dict[str, tuple[str, ...]]:
        """Map each OKX WebSocket endpoint to the channel kinds it serves.

        Endpoints without channels are not connected at all.
        """
        plan: dict[str, tuple[str, ...]] = {}
        non_candle_channels = tuple(
            channel for channel in self.channels if channel != CANDLE_KIND
        )
        if non_candle_channels:
            plan[self.url] = non_candle_channels
        if CANDLE_KIND in self.channels:
            plan[self.business_url] = (CANDLE_KIND,)
        if not plan:
            raise ValueError("feed requires at least one channel")
        return plan

    async def run(self) -> None:
        while not self._stopping:
            plan = self._endpoint_plan()
            connections: dict[str, Connection] = {}
            try:
                for endpoint_url in plan:
                    connections[endpoint_url] = await self.connection_factory(endpoint_url)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.stats["reconnects"] += 1
                if not self.reconnect_delays_seconds:
                    return
                await self._sleep(self._next_backoff())
                continue
            self._backoff_index = 0
            self._awaiting_pong = {endpoint_url: False for endpoint_url in connections}
            self._connections = connections
            supervision = asyncio.create_task(self._supervise(connections))
            try:
                for endpoint_url, connection in connections.items():
                    await self._subscribe(connection, plan[endpoint_url])
                receive_tasks = [
                    asyncio.create_task(self._receive_loop(connection, endpoint_url))
                    for endpoint_url, connection in connections.items()
                ]
                await asyncio.gather(*receive_tasks, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                if supervision is not None:
                    supervision.cancel()
                    with contextlib.suppress(Exception):
                        await supervision
                self._connections = {}
                for connection in connections.values():
                    with contextlib.suppress(Exception):
                        await connection.close()
                await self._mark_disconnected()
            if self._stopping:
                break
            if not self.reconnect_delays_seconds:
                return
            self.stats["reconnects"] += 1
            await self._sleep(self._next_backoff())

    def _is_resident(self, interval: str) -> bool:
        return interval in self.candle_intervals

    def active_candle_channel_count(self) -> int:
        return len(self.instruments) * len(self.candle_intervals) + len(self._dynamic_owners)

    def _candle_active(self, instrument_id: str, interval: str) -> bool:
        return self._is_resident(interval) or (instrument_id, interval) in self._dynamic_owners

    async def acquire_candle(self, owner: str, instrument_id: str, interval: str) -> None:
        """Reference one candle channel for ``owner`` (idempotent per owner)."""
        if instrument_id not in self.instruments:
            raise ValueError(f"instrument is not served by the feed: {instrument_id}")
        if interval not in OKX_CHANNEL:
            raise ValueError(f"unsupported candle interval: {interval}")
        if CANDLE_KIND not in self.channels or self._is_resident(interval):
            return
        key = (instrument_id, interval)
        owners = self._dynamic_owners.get(key)
        if owners is None:
            if self.active_candle_channel_count() >= self.max_candle_channels:
                raise SubscriptionLimitError(
                    f"candle channel limit reached ({self.max_candle_channels})"
                )
            owners = self._dynamic_owners[key] = set()
            await self._send_candle_op("subscribe", key)
        owners.add(owner)
        grace = self._grace_tasks.pop(key, None)
        if grace is not None:
            grace.cancel()

    def release_candle(self, owner: str, instrument_id: str, interval: str) -> None:
        key = (instrument_id, interval)
        owners = self._dynamic_owners.get(key)
        if owners is None:
            return
        owners.discard(owner)
        if not owners and key not in self._grace_tasks:
            self._grace_tasks[key] = asyncio.create_task(self._grace_release(key))

    def release_owner(self, owner: str) -> None:
        for instrument_id, interval in tuple(self._dynamic_owners):
            self.release_candle(owner, instrument_id, interval)

    async def _grace_release(self, key: tuple[str, str]) -> None:
        try:
            await asyncio.sleep(self.candle_grace_seconds)
        except asyncio.CancelledError:
            return
        self._grace_tasks.pop(key, None)
        if self._dynamic_owners.get(key):
            return
        self._dynamic_owners.pop(key, None)
        await self._send_candle_op("unsubscribe", key)

    async def _send_candle_op(self, op: str, key: tuple[str, str]) -> None:
        connection = self._connections.get(self.business_url)
        if connection is None:
            return  # subscribed from the active set on (re)connect
        argument = {"channel": OKX_CHANNEL[key[1]], "instId": _okx_instrument(key[0])}
        with contextlib.suppress(Exception):
            await connection.send(json.dumps({"op": op, "args": [argument]}))

    async def stop(self) -> None:
        self._stopping = True
        for task in tuple(self._grace_tasks.values()):
            task.cancel()
        self._grace_tasks.clear()
        for connection in tuple(self._connections.values()):
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

    async def _subscribe(self, connection: Connection, channels: Iterable[str]) -> None:
        arguments = self._subscription_arguments(channels)
        if not arguments:
            raise ValueError("feed produced no subscription arguments")
        await connection.send(json.dumps({"op": "subscribe", "args": arguments}))

    def _subscription_arguments(self, channels: Iterable[str]) -> list[dict[str, str]]:
        arguments: list[dict[str, str]] = []
        for instrument_id in self.instruments:
            instrument = _okx_instrument(instrument_id)
            for channel in channels:
                if channel == CANDLE_KIND:
                    for interval in self.candle_intervals:
                        arguments.append(
                            {"channel": OKX_CHANNEL[interval], "instId": instrument}
                        )
                    for dyn_instrument, dyn_interval in self._dynamic_owners:
                        if dyn_instrument == instrument_id:
                            arguments.append(
                                {"channel": OKX_CHANNEL[dyn_interval], "instId": instrument}
                            )
                else:
                    arguments.append(
                        {"channel": CHANNEL_REQUEST_NAME[channel], "instId": instrument}
                    )
        return arguments

    async def _resubscribe_order_book(self, instrument: str) -> None:
        connection = self._connections.get(self.url)
        if connection is None:
            return
        argument = {"channel": "books", "instId": _okx_instrument(instrument)}
        await connection.send(json.dumps({"op": "unsubscribe", "args": [argument]}))
        await connection.send(json.dumps({"op": "subscribe", "args": [argument]}))
        self.stats["resynchronizations"] += 1

    async def _receive_loop(self, connection: Connection, endpoint_url: str) -> None:
        while True:
            message = await connection.recv()
            now_ms = self.now_ms()
            self._last_message_ms = now_ms
            self._awaiting_pong[endpoint_url] = False
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
                        self._candle_active(event.instrument_id, event.payload.interval)
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
                await self._resubscribe_order_book(event.instrument_id)
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
        if healthy and self.on_order_book_view is not None:
            await self.on_order_book_view(view)

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
        if valid and self.on_canonical is not None:
            await self.on_canonical(event)

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

    async def _supervise(self, connections: Mapping[str, Connection]) -> None:
        try:
            while True:
                await asyncio.sleep(self.ping_interval_seconds)
                now_ms = self.now_ms()
                if any(self._awaiting_pong.values()):
                    raise ConnectionError("OKX keepalive pong was not received")
                for endpoint_url, connection in connections.items():
                    self._awaiting_pong[endpoint_url] = True
                    await connection.send("ping")
                await self._check_staleness(now_ms)
        except asyncio.CancelledError:
            return
        except Exception:
            # Force a reconnect by closing every endpoint connection.
            for connection in tuple(connections.values()):
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
