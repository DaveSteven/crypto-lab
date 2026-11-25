"""Bounded duplicate and out-of-order detection for canonical events."""

from collections import deque

from crypto_lab.models.common import MarketEventEnvelope
from crypto_lab.models.enums import EventOrderingResult


class EventSequenceTracker:
    def __init__(self, max_event_ids: int = 10_000) -> None:
        if max_event_ids <= 0:
            raise ValueError("max_event_ids must be positive")
        self._max_event_ids = max_event_ids
        self._event_ids: set[str] = set()
        self._event_id_order: deque[str] = deque()
        self._last_exchange_ts: dict[tuple[str, str, str], int] = {}

    def observe(self, event: MarketEventEnvelope[object]) -> EventOrderingResult:
        if event.event_id in self._event_ids:
            return EventOrderingResult.DUPLICATE

        self._event_ids.add(event.event_id)
        self._event_id_order.append(event.event_id)
        if len(self._event_id_order) > self._max_event_ids:
            expired = self._event_id_order.popleft()
            self._event_ids.remove(expired)

        if event.exchange_ts_ms is None:
            return EventOrderingResult.ACCEPTED
        key = (event.exchange_id.value, event.instrument_id, event.event_type)
        previous_ts = self._last_exchange_ts.get(key)
        if previous_ts is not None and event.exchange_ts_ms < previous_ts:
            return EventOrderingResult.OUT_OF_ORDER
        self._last_exchange_ts[key] = event.exchange_ts_ms
        return EventOrderingResult.ACCEPTED
