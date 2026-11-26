"""Replaceable clocks and latency configuration for deterministic execution."""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field, model_validator

from crypto_lab.trading.models import FrozenModel, utc_now_ms


@runtime_checkable
class Clock(Protocol):
    def now_utc_ms(self) -> int: ...

    def monotonic_ms(self) -> int: ...


class SystemClock:
    def now_utc_ms(self) -> int:
        return utc_now_ms()

    def monotonic_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000


class ManualClock:
    def __init__(self, utc_ms: int, *, monotonic_ms: int = 0) -> None:
        self._require_nonnegative(utc_ms, "utc_ms")
        self._require_nonnegative(monotonic_ms, "monotonic_ms")
        self._utc_ms = utc_ms
        self._monotonic_ms = monotonic_ms

    def now_utc_ms(self) -> int:
        return self._utc_ms

    def monotonic_ms(self) -> int:
        return self._monotonic_ms

    def snapshot_state(self) -> tuple[int, int]:
        return (self._utc_ms, self._monotonic_ms)

    def restore_state(self, state: tuple[int, int]) -> None:
        self._utc_ms, self._monotonic_ms = state

    def advance(self, milliseconds: int) -> None:
        self._require_nonnegative(milliseconds, "milliseconds")
        self._utc_ms += milliseconds
        self._monotonic_ms += milliseconds

    def set_utc_ms(self, value: int) -> None:
        self._require_nonnegative(value, "value")
        if value < self._utc_ms:
            raise ValueError("manual UTC clock cannot move backwards")
        self._monotonic_ms += value - self._utc_ms
        self._utc_ms = value

    @staticmethod
    def _require_nonnegative(value: int, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be int")
        if value < 0:
            raise ValueError(f"{name} cannot be negative")


class LatencyPreset(StrEnum):
    IDEAL = "IDEAL"
    FAST = "FAST"
    NORMAL = "NORMAL"
    MEDIUM = "MEDIUM"
    SLOW = "SLOW"
    HIGH = "HIGH"
    CUSTOM = "CUSTOM"


PRESET_LATENCY_MS: dict[LatencyPreset, int] = {
    LatencyPreset.IDEAL: 0,
    LatencyPreset.FAST: 50,
    LatencyPreset.NORMAL: 100,
    LatencyPreset.MEDIUM: 250,
    LatencyPreset.SLOW: 500,
    LatencyPreset.HIGH: 1_000,
}


class ExecutionLatency(FrozenModel):
    preset: LatencyPreset = LatencyPreset.NORMAL
    custom_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_custom_latency(self) -> ExecutionLatency:
        if self.preset is LatencyPreset.CUSTOM and self.custom_ms is None:
            raise ValueError("CUSTOM latency requires custom_ms")
        if self.preset is not LatencyPreset.CUSTOM and self.custom_ms is not None:
            raise ValueError("custom_ms is only valid for CUSTOM latency")
        return self

    @property
    def milliseconds(self) -> int:
        if self.preset is LatencyPreset.CUSTOM:
            assert self.custom_ms is not None
            return self.custom_ms
        return PRESET_LATENCY_MS[self.preset]
