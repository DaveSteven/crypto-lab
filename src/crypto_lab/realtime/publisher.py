"""Non-blocking bridge from committed synchronous transactions to the async hub."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future

from crypto_lab.realtime.hub import RealtimeEvent, RealtimeHubRegistry


class RealtimePublisher:
    def __init__(self, registry: RealtimeHubRegistry) -> None:
        self.registry = registry
        self.loop: asyncio.AbstractEventLoop | None = None
        self.publish_failures = 0
        self.unavailable_publishes = 0

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def stop(self) -> None:
        self.loop = None

    def publish_committed(
        self, environment_id: str, events: tuple[object, ...]
    ) -> None:
        loop = self.loop
        if loop is None or loop.is_closed():
            self.unavailable_publishes += len(events)
            return
        for event in events:
            if not isinstance(event, RealtimeEvent):
                self.publish_failures += 1
                continue
            future = asyncio.run_coroutine_threadsafe(
                self.registry.publish(environment_id, event), loop
            )
            future.add_done_callback(self._observe_result)

    def _observe_result(self, future: Future[object]) -> None:
        try:
            future.result()
        except Exception:
            self.publish_failures += 1
