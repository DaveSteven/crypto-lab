"""Deterministic serial event processing for one simulation environment."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import Field

from crypto_lab.trading.models import FrozenModel
from crypto_lab.trading.unit_of_work import InMemoryUnitOfWork


class SimulationEventKind(StrEnum):
    MARKET_DATA = "MARKET_DATA"
    TRADE = "TRADE"
    ORDER_SUBMISSION = "ORDER_SUBMISSION"
    ORDER_CANCELLATION = "ORDER_CANCELLATION"
    SCHEDULED_EXECUTION = "SCHEDULED_EXECUTION"
    PASSIVE_MATCHING = "PASSIVE_MATCHING"


class EventProcessingStatus(StrEnum):
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"


class SimulationEvent(FrozenModel):
    event_id: str = Field(min_length=1)
    timestamp_ms: int = Field(ge=0)
    kind: SimulationEventKind
    arrival_sequence: int = Field(gt=0)


class EventProcessingResult(FrozenModel):
    event: SimulationEvent
    status: EventProcessingStatus
    value: Any = None


EventHandler = Callable[[], Any]


class SerialEventProcessor:
    """One non-concurrent event stream; market data wins equal timestamps."""

    def __init__(
        self,
        simulation_environment_id: str,
        unit_of_work: InMemoryUnitOfWork,
        *,
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not simulation_environment_id:
            raise ValueError("simulation environment ID is required")
        self.simulation_environment_id = simulation_environment_id
        self.unit_of_work = unit_of_work
        self.failure_injector = failure_injector
        self._pending: dict[str, tuple[SimulationEvent, EventHandler]] = {}
        self._processed: dict[str, EventProcessingResult] = {}
        self._next_arrival_sequence = 1
        self._last_timestamp_ms: int | None = None
        self.unit_of_work.add_participant(self)

    def enqueue(
        self,
        *,
        event_id: str,
        timestamp_ms: int,
        kind: SimulationEventKind,
        handler: EventHandler,
    ) -> SimulationEvent:
        if event_id in self._pending or event_id in self._processed:
            raise ValueError("event ID already exists in this simulation environment")
        event = SimulationEvent(
            event_id=event_id,
            timestamp_ms=timestamp_ms,
            kind=kind,
            arrival_sequence=self._next_arrival_sequence,
        )
        self._next_arrival_sequence += 1
        self._pending[event_id] = (event, handler)
        return event

    def pending(self) -> tuple[SimulationEvent, ...]:
        return tuple(item[0] for item in sorted(self._pending.values(), key=self._sort_key))

    def result(self, event_id: str) -> EventProcessingResult | None:
        return self._processed.get(event_id)

    def process_next(self) -> EventProcessingResult | None:
        ordered = self.pending()
        if not ordered:
            return None
        event = ordered[0]
        if self._last_timestamp_ms is not None and event.timestamp_ms < self._last_timestamp_ms:
            result = EventProcessingResult(
                event=event,
                status=EventProcessingStatus.OUT_OF_ORDER,
            )
            self._pending.pop(event.event_id)
            self._processed[event.event_id] = result
            return result

        def process() -> EventProcessingResult:
            _, handler = self._pending[event.event_id]
            value = handler()
            result = EventProcessingResult(
                event=event,
                status=EventProcessingStatus.PROCESSED,
                value=value,
            )
            self._pending.pop(event.event_id)
            self._processed[event.event_id] = result
            self._last_timestamp_ms = event.timestamp_ms
            if self.failure_injector is not None:
                self.failure_injector("EVENT_REGISTRY")
            return result

        return self.unit_of_work.run(process)

    def process_all(self) -> tuple[EventProcessingResult, ...]:
        results: list[EventProcessingResult] = []
        while self._pending:
            result = self.process_next()
            assert result is not None
            results.append(result)
        return tuple(results)

    def snapshot_state(
        self,
    ) -> tuple[
        dict[str, tuple[SimulationEvent, EventHandler]],
        dict[str, EventProcessingResult],
        int,
        int | None,
    ]:
        return (
            self._pending.copy(),
            self._processed.copy(),
            self._next_arrival_sequence,
            self._last_timestamp_ms,
        )

    def restore_state(
        self,
        state: tuple[
            dict[str, tuple[SimulationEvent, EventHandler]],
            dict[str, EventProcessingResult],
            int,
            int | None,
        ],
    ) -> None:
        pending, processed, next_sequence, last_timestamp = state
        self._pending = pending.copy()
        self._processed = processed.copy()
        self._next_arrival_sequence = next_sequence
        self._last_timestamp_ms = last_timestamp

    @staticmethod
    def _sort_key(item: tuple[SimulationEvent, EventHandler]) -> tuple[int, int, int]:
        event = item[0]
        market_priority = 0 if event.kind is SimulationEventKind.MARKET_DATA else 1
        return (event.timestamp_ms, market_priority, event.arrival_sequence)
