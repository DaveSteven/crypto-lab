"""Snapshot/restore transaction boundary for in-memory trading state."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol, TypeVar


class SnapshotParticipant(Protocol):
    def snapshot_state(self) -> Any: ...

    def restore_state(self, state: Any) -> None: ...


ResultT = TypeVar("ResultT")


class InMemoryUnitOfWork:
    """Roll back every participant when an operation or commit hook fails."""

    def __init__(self, participants: Iterable[SnapshotParticipant]) -> None:
        unique: list[SnapshotParticipant] = []
        seen: set[int] = set()
        for participant in participants:
            identity = id(participant)
            if identity not in seen:
                unique.append(participant)
                seen.add(identity)
        if not unique:
            raise ValueError("unit of work requires at least one participant")
        self._participants = tuple(unique)

    def add_participant(self, participant: SnapshotParticipant) -> None:
        if all(existing is not participant for existing in self._participants):
            self._participants = (*self._participants, participant)

    def run(
        self,
        operation: Callable[[], ResultT],
        *,
        before_commit: Callable[[], None] | None = None,
    ) -> ResultT:
        snapshots = tuple(
            (participant, participant.snapshot_state()) for participant in self._participants
        )
        try:
            result = operation()
            if before_commit is not None:
                before_commit()
            return result
        except BaseException:
            for participant, state in reversed(snapshots):
                participant.restore_state(state)
            raise
