import pytest

from crypto_lab.trading import (
    EventProcessingStatus,
    InMemoryUnitOfWork,
    SerialEventProcessor,
    SimulationEventKind,
)


class MutableState:
    def __init__(self) -> None:
        self.values: list[str] = []

    def snapshot_state(self) -> list[str]:
        return self.values.copy()

    def restore_state(self, state: list[str]) -> None:
        self.values = state.copy()


def processor() -> tuple[MutableState, SerialEventProcessor]:
    state = MutableState()
    uow = InMemoryUnitOfWork((state,))
    return state, SerialEventProcessor("run-1", uow)


def test_equal_timestamp_market_data_precedes_commands_then_arrival_order_wins() -> None:
    state, events = processor()
    events.enqueue(
        event_id="execute",
        timestamp_ms=1_000,
        kind=SimulationEventKind.SCHEDULED_EXECUTION,
        handler=lambda: state.values.append("execute"),
    )
    events.enqueue(
        event_id="cancel",
        timestamp_ms=1_000,
        kind=SimulationEventKind.ORDER_CANCELLATION,
        handler=lambda: state.values.append("cancel"),
    )
    events.enqueue(
        event_id="market",
        timestamp_ms=1_000,
        kind=SimulationEventKind.MARKET_DATA,
        handler=lambda: state.values.append("market"),
    )

    events.process_all()

    assert state.values == ["market", "execute", "cancel"]


def test_cancel_and_execution_competition_is_decided_by_arrival_sequence() -> None:
    state, events = processor()
    events.enqueue(
        event_id="cancel-first",
        timestamp_ms=1_000,
        kind=SimulationEventKind.ORDER_CANCELLATION,
        handler=lambda: state.values.append("cancel"),
    )
    events.enqueue(
        event_id="execute-second",
        timestamp_ms=1_000,
        kind=SimulationEventKind.SCHEDULED_EXECUTION,
        handler=lambda: state.values.append("execute"),
    )

    events.process_all()

    assert state.values == ["cancel", "execute"]


def test_failed_event_rolls_back_state_and_is_not_marked_processed() -> None:
    state, events = processor()

    def fail_after_mutation() -> None:
        state.values.append("partial")
        raise RuntimeError("injected event failure")

    event = events.enqueue(
        event_id="retryable",
        timestamp_ms=1_000,
        kind=SimulationEventKind.SCHEDULED_EXECUTION,
        handler=fail_after_mutation,
    )

    with pytest.raises(RuntimeError, match="injected"):
        events.process_next()

    assert state.values == []
    assert events.result(event.event_id) is None
    assert events.pending() == (event,)


def test_event_registry_failure_rolls_back_handler_and_processed_marker() -> None:
    state = MutableState()

    def inject(stage: str) -> None:
        if stage == "EVENT_REGISTRY":
            raise RuntimeError("injected event registry failure")

    events = SerialEventProcessor(
        "run-1",
        InMemoryUnitOfWork((state,)),
        failure_injector=inject,
    )
    event = events.enqueue(
        event_id="registry-failure",
        timestamp_ms=1_000,
        kind=SimulationEventKind.TRADE,
        handler=lambda: state.values.append("mutation"),
    )

    with pytest.raises(RuntimeError, match="registry"):
        events.process_next()

    assert state.values == []
    assert events.result(event.event_id) is None
    assert events.pending() == (event,)


def test_duplicate_and_out_of_order_events_have_explicit_results() -> None:
    _, events = processor()
    events.enqueue(
        event_id="newer",
        timestamp_ms=2_000,
        kind=SimulationEventKind.TRADE,
        handler=lambda: None,
    )
    events.process_next()
    events.enqueue(
        event_id="older",
        timestamp_ms=1_000,
        kind=SimulationEventKind.TRADE,
        handler=lambda: None,
    )

    result = events.process_next()

    assert result is not None
    assert result.status is EventProcessingStatus.OUT_OF_ORDER
    with pytest.raises(ValueError, match="already exists"):
        events.enqueue(
            event_id="newer",
            timestamp_ms=2_001,
            kind=SimulationEventKind.TRADE,
            handler=lambda: None,
        )
