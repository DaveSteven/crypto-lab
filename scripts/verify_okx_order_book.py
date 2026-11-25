#!/usr/bin/env python3
"""Run a bounded live verification of the OKX canonical order-book adapter."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from websockets.asyncio.client import connect

from crypto_lab.market_data import OrderBookMarketState, normalize_okx_order_book
from crypto_lab.models import OrderBookDelta, OrderBookSnapshot
from crypto_lab.trading import normalize_okx_spot_rules

OKX_WS_URL: Final = "wss://ws.okx.com/ws/v5/public"
OKX_INSTRUMENTS_URL: Final = "https://www.okx.com/api/v5/public/instruments"
MAX_MESSAGE_BYTES: Final = 2_000_000


@dataclass
class VerificationReport:
    status: str
    instrument: str
    started_ts_ms: int
    completed_ts_ms: int
    duration_ms: int
    configured_duration_seconds: float
    max_messages: int
    max_raw_bytes: int
    message_count: int
    snapshot_count: int
    delta_count: int
    normalized_event_count: int
    final_sequence_id: str | None
    final_book_age_ms: int | None
    market_rules: dict[str, object] | None
    raw_output: str
    raw_bytes_written: int
    error_type: str | None = None
    error_message: str | None = None


class BoundedJsonlWriter:
    def __init__(self, path: Path, max_bytes: int) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.bytes_written = 0
        self._file = None

    def __enter__(self) -> BoundedJsonlWriter:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("wb")
        return self

    def write(self, payload: object) -> None:
        if self._file is None:
            raise RuntimeError("writer is not open")
        encoded = json.dumps(payload, separators=(",", ":")).encode() + b"\n"
        if self.bytes_written + len(encoded) > self.max_bytes:
            raise RuntimeError("raw output capacity reached")
        self._file.write(encoded)
        self.bytes_written += len(encoded)

    def __exit__(self, *_: object) -> None:
        if self._file is not None:
            self._file.close()


def fetch_market_rules(instrument: str, timeout_seconds: float) -> dict[str, object]:
    query = urllib.parse.urlencode({"instType": "SPOT", "instId": instrument})
    request = urllib.request.Request(
        f"{OKX_INSTRUMENTS_URL}?{query}",
        headers={"User-Agent": "crypto-lab/0.1"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.load(response)
    observed_ts_ms = time.time_ns() // 1_000_000
    rules = normalize_okx_spot_rules(
        payload,
        instrument=instrument,
        observed_ts_ms=observed_ts_ms,
    )
    return rules.model_dump(mode="json")


async def verify(
    *,
    instrument: str,
    duration_seconds: float,
    max_messages: int,
    raw_output: Path,
    max_raw_bytes: int,
) -> VerificationReport:
    started_ts_ms = time.time_ns() // 1_000_000
    started_monotonic = time.monotonic()
    message_count = snapshot_count = delta_count = normalized_count = 0
    final_sequence_id: str | None = None
    final_book_age_ms: int | None = None
    market_rules: dict[str, object] | None = None
    error_type = error_message = None
    state = OrderBookMarketState()
    instrument_id = f"okx:SPOT:{instrument.replace('-', '/')}"

    try:
        market_rules = await asyncio.to_thread(
            fetch_market_rules,
            instrument,
            min(10.0, duration_seconds),
        )
        deadline = asyncio.get_running_loop().time() + duration_seconds
        with BoundedJsonlWriter(raw_output, max_raw_bytes) as writer:
            async with connect(
                OKX_WS_URL,
                open_timeout=10,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=10,
                max_size=MAX_MESSAGE_BYTES,
            ) as websocket:
                await websocket.send(
                    json.dumps(
                        {
                            "op": "subscribe",
                            "args": [{"channel": "books", "instId": instrument}],
                        },
                        separators=(",", ":"),
                    )
                )
                while message_count < max_messages:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        raw = await asyncio.wait_for(websocket.recv(), timeout=min(remaining, 2))
                    except TimeoutError:
                        continue
                    if not isinstance(raw, str):
                        continue
                    payload = json.loads(raw)
                    writer.write(payload)
                    message_count += 1
                    if not isinstance(payload, dict) or payload.get("action") not in {
                        "snapshot",
                        "update",
                    }:
                        continue
                    received_ts_ms = time.time_ns() // 1_000_000
                    event = normalize_okx_order_book(payload, received_ts_ms=received_ts_ms)
                    normalized_count += 1
                    if isinstance(event.payload, OrderBookSnapshot):
                        snapshot_count += 1
                        view = state.apply_snapshot(event)
                    elif isinstance(event.payload, OrderBookDelta):
                        delta_count += 1
                        view = state.apply_delta(event)
                    final_sequence_id = view.sequence_id

            completed_for_age_ms = time.time_ns() // 1_000_000
            executable = state.executable_book(
                view.exchange_id,
                instrument_id,
                decision_ts_ms=completed_for_age_ms,
                max_age_ms=2_000,
            )
            final_book_age_ms = completed_for_age_ms - executable.received_ts_ms
            raw_bytes_written = writer.bytes_written
        status = (
            "VERIFIED"
            if snapshot_count >= 1 and delta_count >= 1 and normalized_count >= 2
            else "PARTIAL"
        )
    except Exception as exc:  # noqa: BLE001 - report bounded verification failures
        status = "FAILED"
        error_type = type(exc).__name__
        error_message = str(exc)
        raw_bytes_written = raw_output.stat().st_size if raw_output.exists() else 0

    completed_ts_ms = time.time_ns() // 1_000_000
    return VerificationReport(
        status=status,
        instrument=instrument,
        started_ts_ms=started_ts_ms,
        completed_ts_ms=completed_ts_ms,
        duration_ms=int((time.monotonic() - started_monotonic) * 1_000),
        configured_duration_seconds=duration_seconds,
        max_messages=max_messages,
        max_raw_bytes=max_raw_bytes,
        message_count=message_count,
        snapshot_count=snapshot_count,
        delta_count=delta_count,
        normalized_event_count=normalized_count,
        final_sequence_id=final_sequence_id,
        final_book_age_ms=final_book_age_ms,
        market_rules=market_rules,
        raw_output=str(raw_output),
        raw_bytes_written=raw_bytes_written,
        error_type=error_type,
        error_message=error_message,
    )


def default_report_path() -> Path:
    now = datetime.now(UTC)
    return Path("data/verification") / f"okx-order-book-{now:%Y%m%d-%H%M%S}.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instrument", default="BTC-USDT")
    parser.add_argument("--duration-seconds", type=float, default=15.0)
    parser.add_argument("--max-messages", type=int, default=1_000)
    parser.add_argument("--max-raw-bytes", type=int, default=2_000_000)
    parser.add_argument("--report-output", type=Path, default=None)
    parser.add_argument("--raw-output", type=Path, default=None)
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args()
    if args.duration_seconds <= 0 or args.max_messages <= 0 or args.max_raw_bytes <= 0:
        parser.error("duration, message limit, and raw byte limit must be positive")
    logging.basicConfig(level=args.log_level.upper())

    report_output = args.report_output or default_report_path()
    raw_output = args.raw_output or report_output.with_suffix(".jsonl")
    report = asyncio.run(
        verify(
            instrument=args.instrument,
            duration_seconds=args.duration_seconds,
            max_messages=args.max_messages,
            raw_output=raw_output,
            max_raw_bytes=args.max_raw_bytes,
        )
    )
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"status={report.status} report={report_output}")
    return 0 if report.status == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
