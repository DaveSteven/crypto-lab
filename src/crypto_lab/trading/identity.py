"""Business identity generators for reproducible simulation runs."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import NAMESPACE_URL, uuid4, uuid5


@runtime_checkable
class IdGenerator(Protocol):
    def next_id(self, kind: str) -> str: ...


class RandomIdGenerator:
    def next_id(self, kind: str) -> str:
        if not kind:
            raise ValueError("ID kind is required")
        return str(uuid4())


class DeterministicIdGenerator:
    def __init__(self, namespace: str) -> None:
        if not namespace:
            raise ValueError("ID namespace is required")
        self.namespace = namespace
        self._counters: dict[str, int] = {}

    def next_id(self, kind: str) -> str:
        if not kind:
            raise ValueError("ID kind is required")
        sequence = self._counters.get(kind, 0) + 1
        self._counters[kind] = sequence
        return str(uuid5(NAMESPACE_URL, f"crypto-lab:{self.namespace}:{kind}:{sequence}"))

    def snapshot_state(self) -> dict[str, int]:
        return self._counters.copy()

    def restore_state(self, state: dict[str, int]) -> None:
        self._counters = state.copy()
