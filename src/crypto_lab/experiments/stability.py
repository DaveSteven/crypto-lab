"""Storage and episode tracking for bounded stability experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from crypto_lab.models import SpreadObservation


class StorageLimitReachedError(RuntimeError):
    pass


class RotatingJsonlWriter:
    def __init__(self, directory: Path, prefix: str, rotate_bytes: int, max_bytes: int) -> None:
        if rotate_bytes <= 0 or max_bytes <= 0 or rotate_bytes > max_bytes:
            raise ValueError("storage limits must satisfy 0 < rotate_bytes <= max_bytes")
        self.directory = directory
        self.prefix = prefix
        self.rotate_bytes = rotate_bytes
        self.max_bytes = max_bytes
        self.total_bytes = 0
        self.file_count = 0
        self._current_bytes = 0
        self._file: TextIO | None = None
        directory.mkdir(parents=True, exist_ok=True)

    def _open_next(self) -> None:
        if self._file is not None:
            self._file.close()
        self.file_count += 1
        path = self.directory / f"{self.prefix}-{self.file_count:04d}.jsonl"
        self._file = path.open("x", encoding="utf-8")
        self._current_bytes = 0

    def write(self, payload: dict) -> None:
        encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        if self.total_bytes + len(encoded) > self.max_bytes:
            raise StorageLimitReachedError("experiment storage limit reached")
        if self._file is None or self._current_bytes + len(encoded) > self.rotate_bytes:
            self._open_next()
        assert self._file is not None
        self._file.write(encoded.decode())
        self._file.flush()
        self._current_bytes += len(encoded)
        self.total_bytes += len(encoded)

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> RotatingJsonlWriter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass
class Episode:
    started_ts_ms: int
    last_seen_ts_ms: int
    samples: int = 1


class GrossSpreadEpisodes:
    """Track contiguous positive-gross observations per directed route."""

    def __init__(self, max_gap_ms: int) -> None:
        if max_gap_ms <= 0:
            raise ValueError("max_gap_ms must be positive")
        self.max_gap_ms = max_gap_ms
        self.active: dict[tuple[str, str], Episode] = {}
        self.completed_count = 0
        self.completed_duration_ms = 0

    def observe(self, observations: list[SpreadObservation], observed_ts_ms: int) -> None:
        positive_routes = {
            (item.buy_exchange_id.value, item.sell_exchange_id.value)
            for item in observations
            if item.quality_status.value == "VALID" and item.gross_spread > 0
        }
        for route in list(self.active):
            episode = self.active[route]
            gap_ms = observed_ts_ms - episode.last_seen_ts_ms
            if route not in positive_routes or gap_ms > self.max_gap_ms:
                self._complete(route)
        for route in positive_routes:
            episode = self.active.get(route)
            if episode is None:
                self.active[route] = Episode(observed_ts_ms, observed_ts_ms)
            else:
                episode.last_seen_ts_ms = observed_ts_ms
                episode.samples += 1

    def _complete(self, route: tuple[str, str]) -> None:
        episode = self.active.pop(route)
        self.completed_count += 1
        self.completed_duration_ms += episode.last_seen_ts_ms - episode.started_ts_ms

    def finish(self) -> None:
        for route in list(self.active):
            self._complete(route)
