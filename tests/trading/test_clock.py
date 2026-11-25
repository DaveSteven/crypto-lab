import pytest
from pydantic import ValidationError

from crypto_lab.trading import ExecutionLatency, LatencyPreset, ManualClock, SystemClock


def test_manual_clock_advances_utc_and_monotonic_time_without_waiting() -> None:
    clock = ManualClock(1_000, monotonic_ms=25)

    clock.advance(100)

    assert clock.now_utc_ms() == 1_100
    assert clock.monotonic_ms() == 125


def test_manual_clock_cannot_move_backwards() -> None:
    clock = ManualClock(1_000)

    with pytest.raises(ValueError, match="backwards"):
        clock.set_utc_ms(999)


def test_system_clock_exposes_utc_and_monotonic_time() -> None:
    clock = SystemClock()

    assert clock.now_utc_ms() > 0
    assert clock.monotonic_ms() > 0


@pytest.mark.parametrize(
    ("preset", "milliseconds"),
    [
        (LatencyPreset.IDEAL, 0),
        (LatencyPreset.FAST, 50),
        (LatencyPreset.NORMAL, 100),
        (LatencyPreset.MEDIUM, 250),
        (LatencyPreset.SLOW, 500),
        (LatencyPreset.HIGH, 1_000),
    ],
)
def test_latency_presets_are_explicit(preset: LatencyPreset, milliseconds: int) -> None:
    assert ExecutionLatency(preset=preset).milliseconds == milliseconds


def test_custom_latency_requires_explicit_nonnegative_value() -> None:
    assert ExecutionLatency(preset=LatencyPreset.CUSTOM, custom_ms=375).milliseconds == 375
    with pytest.raises(ValidationError, match="custom_ms"):
        ExecutionLatency(preset=LatencyPreset.CUSTOM)
    with pytest.raises(ValidationError, match="only valid"):
        ExecutionLatency(preset=LatencyPreset.NORMAL, custom_ms=100)
