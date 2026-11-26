"""Environment-scoped event streams with bounded replay and connection buffers."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from crypto_lab.trading.clock import Clock, SystemClock


class RealtimeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    topic: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    event_ts_ms: int = Field(ge=0)
    payload: dict[str, Any]
    instrument_id: str | None = None
    account_id: str | None = None
    order_id: str | None = None
    interval: str | None = None
    candle_open_ts_ms: int | None = Field(default=None, ge=0)
    candle_closed: bool | None = None
    state_version: int | None = Field(default=None, ge=0)
    transaction_id: str | None = None
    event_index: int | None = Field(default=None, ge=0)
    coalescible: bool = False

    @property
    def coalescing_key(self) -> tuple[object, ...]:
        return (
            self.topic,
            self.instrument_id,
            self.account_id,
            self.interval,
            self.candle_open_ts_ms,
        )


class StreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: str = "1.0.0"
    type: str
    environment_id: str
    stream_id: str
    stream_sequence: int = Field(gt=0)
    event_id: str
    event_ts_ms: int
    published_ts_ms: int
    payload: dict[str, Any]
    instrument_id: str | None = None
    account_id: str | None = None
    order_id: str | None = None
    interval: str | None = None
    state_version: int | None = None
    transaction_id: str | None = None
    event_index: int | None = None
    coalescible: bool = False
    coalescing_key: tuple[object, ...]


class Subscription(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    instrument_id: str | None = None
    account_id: str | None = None
    order_id: str | None = None
    interval: str | None = None

    def matches(self, event: StreamEvent) -> bool:
        return (
            self.name == event.type
            and (self.instrument_id is None or self.instrument_id == event.instrument_id)
            and (self.account_id is None or self.account_id == event.account_id)
            and (self.order_id is None or self.order_id == event.order_id)
            and (self.interval is None or self.interval == event.interval)
        )


@dataclass(frozen=True)
class RealtimeConfig:
    connection_queue_capacity: int = 256
    replay_max_events: int = 1_000
    replay_max_age_ms: int = 60_000
    global_replay_max_events: int = 10_000
    max_connections: int = 100
    max_connections_per_environment: int = 20
    max_subscriptions_per_connection: int = 50
    heartbeat_interval_ms: int = 15_000
    client_timeout_ms: int = 45_000
    send_timeout_ms: int = 5_000


class SlowConsumer(RuntimeError):
    pass


class ReplayUnavailable(RuntimeError):
    pass


class ConnectionBuffer:
    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._items: deque[StreamEvent] = deque()
        self._condition = asyncio.Condition()
        self.coalesced_count = 0
        self.dropped_market_count = 0
        self.high_watermark = 0
        self.closed = False

    async def put(self, event: StreamEvent) -> None:
        async with self._condition:
            if self.closed:
                return
            if event.coalescible:
                for index, queued in enumerate(self._items):
                    if queued.coalescible and queued.coalescing_key == event.coalescing_key:
                        self._items[index] = event
                        self.coalesced_count += 1
                        self._condition.notify()
                        return
            if len(self._items) >= self.capacity:
                if event.coalescible:
                    for index, queued in enumerate(self._items):
                        if queued.coalescible:
                            del self._items[index]
                            self.dropped_market_count += 1
                            break
                    else:
                        self.dropped_market_count += 1
                        return
                else:
                    raise SlowConsumer("reliable event cannot fit in connection queue")
            self._items.append(event)
            self.high_watermark = max(self.high_watermark, len(self._items))
            self._condition.notify()

    async def get(self) -> StreamEvent:
        async with self._condition:
            while not self._items and not self.closed:
                await self._condition.wait()
            if not self._items:
                raise asyncio.CancelledError
            return self._items.popleft()

    async def close(self) -> None:
        async with self._condition:
            self.closed = True
            self._items.clear()
            self._condition.notify_all()

    def snapshot(self) -> tuple[StreamEvent, ...]:
        return tuple(self._items)


@dataclass
class RealtimeConnection:
    connection_id: str
    buffer: ConnectionBuffer
    subscriptions: set[Subscription] = field(default_factory=set)
    delivery_sequence: int = 0
    last_client_message_ms: int = 0
    requires_resync: bool = False

    def matches(self, event: StreamEvent) -> bool:
        return any(subscription.matches(event) for subscription in self.subscriptions)

    def deliver(self, event: StreamEvent) -> dict[str, Any]:
        self.delivery_sequence += 1
        value = event.model_dump(mode="json", exclude={"coalescible", "coalescing_key"})
        value["delivery_sequence"] = self.delivery_sequence
        return value


class EnvironmentEventHub:
    def __init__(
        self,
        environment_id: str,
        *,
        config: RealtimeConfig,
        clock: Clock | None = None,
        stream_id: str | None = None,
    ) -> None:
        self.environment_id = environment_id
        self.config = config
        self.clock = clock or SystemClock()
        self.stream_id = stream_id or uuid4().hex
        self._stream_sequence = 0
        self._replay: deque[StreamEvent] = deque()
        self._connections: dict[str, RealtimeConnection] = {}
        self.publish_failures = 0

    @property
    def stream_sequence(self) -> int:
        return self._stream_sequence

    def connect(self) -> RealtimeConnection:
        if len(self._connections) >= self.config.max_connections_per_environment:
            raise ConnectionError("environment connection limit reached")
        connection = RealtimeConnection(
            connection_id=uuid4().hex,
            buffer=ConnectionBuffer(self.config.connection_queue_capacity),
            last_client_message_ms=self.clock.now_utc_ms(),
        )
        self._connections[connection.connection_id] = connection
        return connection

    async def disconnect(self, connection: RealtimeConnection) -> None:
        self._connections.pop(connection.connection_id, None)
        await connection.buffer.close()

    def subscribe(
        self, connection: RealtimeConnection, subscriptions: set[Subscription]
    ) -> None:
        combined = connection.subscriptions | subscriptions
        if len(combined) > self.config.max_subscriptions_per_connection:
            raise ValueError("subscription limit reached")
        connection.subscriptions = combined

    def unsubscribe(
        self, connection: RealtimeConnection, subscriptions: set[Subscription]
    ) -> None:
        connection.subscriptions -= subscriptions

    async def publish(self, event: RealtimeEvent) -> StreamEvent:
        self._stream_sequence += 1
        published = StreamEvent(
            type=event.topic,
            environment_id=self.environment_id,
            stream_id=self.stream_id,
            stream_sequence=self._stream_sequence,
            event_id=event.event_id,
            event_ts_ms=event.event_ts_ms,
            published_ts_ms=self.clock.now_utc_ms(),
            payload=event.payload,
            instrument_id=event.instrument_id,
            account_id=event.account_id,
            order_id=event.order_id,
            interval=event.interval,
            state_version=event.state_version,
            transaction_id=event.transaction_id,
            event_index=event.event_index,
            coalescible=event.coalescible,
            coalescing_key=event.coalescing_key,
        )
        self._replay.append(published)
        self._trim_replay()
        for connection in tuple(self._connections.values()):
            if not connection.matches(published):
                continue
            try:
                await connection.buffer.put(published)
            except SlowConsumer:
                connection.requires_resync = True
                self.publish_failures += 1
        return published

    async def replay(
        self,
        connection: RealtimeConnection,
        *,
        stream_id: str,
        after_sequence: int,
    ) -> int:
        if stream_id != self.stream_id:
            raise ReplayUnavailable("stream_id is no longer active")
        if after_sequence < 0 or after_sequence > self._stream_sequence:
            raise ReplayUnavailable("invalid replay cursor")
        if self._replay and after_sequence < self._replay[0].stream_sequence - 1:
            raise ReplayUnavailable("replay cursor is outside the buffer")
        upper_bound = self._stream_sequence
        replayed = 0
        for event in tuple(self._replay):
            if after_sequence < event.stream_sequence <= upper_bound and connection.matches(event):
                await connection.buffer.put(event)
                replayed += 1
        return replayed

    def _trim_replay(self) -> None:
        cutoff = self.clock.now_utc_ms() - self.config.replay_max_age_ms
        while self._replay and (
            len(self._replay) > self.config.replay_max_events
            or self._replay[0].published_ts_ms < cutoff
        ):
            self._replay.popleft()

    def stats(self) -> dict[str, int]:
        return {
            "connections": len(self._connections),
            "replay_events": len(self._replay),
            "stream_sequence": self._stream_sequence,
            "publish_failures": self.publish_failures,
        }


class RealtimeHubRegistry:
    def __init__(
        self, config: RealtimeConfig | None = None, *, clock: Clock | None = None
    ) -> None:
        self.config = config or RealtimeConfig()
        self.clock = clock or SystemClock()
        self._hubs: dict[str, EnvironmentEventHub] = {}

    def hub(self, environment_id: str) -> EnvironmentEventHub:
        if environment_id not in self._hubs:
            connection_count = sum(
                hub.stats()["connections"] for hub in self._hubs.values()
            )
            if connection_count >= self.config.max_connections:
                raise ConnectionError("global connection limit reached")
            self._hubs[environment_id] = EnvironmentEventHub(
                environment_id, config=self.config, clock=self.clock
            )
        return self._hubs[environment_id]

    def environment_ids(self) -> tuple[str, ...]:
        return tuple(self._hubs)

    async def publish(self, environment_id: str, event: RealtimeEvent) -> StreamEvent:
        result = await self.hub(environment_id).publish(event)
        self._trim_global_replay()
        return result

    def _trim_global_replay(self) -> None:
        total = sum(hub.stats()["replay_events"] for hub in self._hubs.values())
        if total <= self.config.global_replay_max_events:
            return
        hubs = sorted(self._hubs.values(), key=lambda hub: len(hub._replay), reverse=True)
        for hub in hubs:
            while hub._replay and total > self.config.global_replay_max_events:
                hub._replay.popleft()
                total -= 1
