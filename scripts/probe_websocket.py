#!/usr/bin/env python3
"""Run bounded public WebSocket smoke tests for Phase 0 exchanges."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException


@dataclass(frozen=True)
class ExchangeConfig:
    exchange_id: str
    url: str
    subscriptions: tuple[object, ...]
    socket_io_rooms: tuple[str, ...] = ()


@dataclass
class ProbeState:
    exchange_id: str
    started_ts_ms: int
    completed_ts_ms: int | None = None
    duration_ms: int | None = None
    success: bool = False
    connection_attempts: int = 0
    subscription_ack: bool = False
    heartbeat_ok: bool = False
    ticker_received: bool = False
    order_book_snapshot_received: bool = False
    order_book_delta_received: bool = False
    sequence_checked: bool = False
    sequence_ok: bool = True
    message_count: int = 0
    last_message_age_ms: int | None = None
    stale: bool = True
    synchronization_status: str = "UNVERIFIED"
    error_type: str | None = None
    error_message: str | None = None
    _last_data_monotonic_ns: int | None = field(default=None, repr=False)
    _last_sequence: int | None = field(default=None, repr=False)
    _snapshot_sequence: int | None = field(default=None, repr=False)
    _observation_ended_monotonic_ns: int | None = field(default=None, repr=False)

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {key: value for key, value in data.items() if not key.startswith("_")}


CONFIGS: Final = (
    ExchangeConfig(
        "binance",
        "wss://stream.binance.com:9443/ws",
        (
            {
                "method": "SUBSCRIBE",
                "params": [
                    "btcusdt@bookTicker",
                    "btcusdt@depth5@100ms",
                    "btcusdt@depth@100ms",
                ],
                "id": 1,
            },
        ),
    ),
    ExchangeConfig(
        "okx",
        "wss://ws.okx.com/ws/v5/public",
        (
            {
                "op": "subscribe",
                "args": [
                    {"channel": "tickers", "instId": "BTC-USDT"},
                    {"channel": "books", "instId": "BTC-USDT"},
                ],
            },
        ),
    ),
    ExchangeConfig(
        "bybit",
        "wss://stream.bybit.com/v5/public/spot",
        (
            {
                "op": "subscribe",
                "args": ["tickers.BTCUSDT", "orderbook.50.BTCUSDT"],
            },
            {"req_id": "crypto-lab-probe", "op": "ping"},
        ),
    ),
    ExchangeConfig(
        "kraken",
        "wss://ws.kraken.com/v2",
        (
            {
                "method": "subscribe",
                "params": {"channel": "ticker", "symbol": ["BTC/USDT"], "snapshot": True},
            },
            {
                "method": "subscribe",
                "params": {
                    "channel": "book",
                    "symbol": ["BTC/USDT"],
                    "depth": 10,
                    "snapshot": True,
                },
            },
        ),
    ),
    ExchangeConfig(
        "coinbase",
        "wss://advanced-trade-ws.coinbase.com",
        (
            {
                "type": "subscribe",
                "product_ids": ["BTC-USDT"],
                "channel": "ticker",
            },
            {
                "type": "subscribe",
                "product_ids": ["BTC-USDT"],
                "channel": "level2",
            },
            {
                "type": "subscribe",
                "product_ids": ["BTC-USDT"],
                "channel": "heartbeats",
            },
        ),
    ),
    ExchangeConfig(
        "bitbank",
        "wss://stream.bitbank.cc/socket.io/?EIO=4&transport=websocket",
        (),
        ("ticker_btc_jpy", "depth_whole_btc_jpy", "depth_diff_btc_jpy"),
    ),
)


def _mark_data(state: ProbeState) -> None:
    state.message_count += 1
    state._last_data_monotonic_ns = time.monotonic_ns()


def _check_sequence(
    state: ProbeState,
    current: int,
    previous: int | None = None,
    *,
    contiguous: bool = False,
) -> None:
    if state._last_sequence is not None:
        state.sequence_checked = True
        if previous is not None:
            state.sequence_ok &= previous == state._last_sequence
        elif contiguous:
            state.sequence_ok &= current == state._last_sequence + 1
        else:
            state.sequence_ok &= current >= state._last_sequence
    state._last_sequence = current


def handle_json_message(exchange_id: str, payload: object, state: ProbeState) -> None:
    """Classify one decoded exchange message and check available sequence metadata."""

    if not isinstance(payload, dict):
        return

    if exchange_id == "binance":
        if payload.get("result") is None and "id" in payload:
            state.subscription_ack = True
        elif payload.get("e") == "bookTicker":
            state.ticker_received = True
            _mark_data(state)
        elif payload.get("e") == "depthUpdate":
            state.order_book_delta_received = True
            _check_sequence(state, int(payload["u"]))
            _mark_data(state)
        elif all(key in payload for key in ("u", "s", "b", "B", "a", "A")):
            state.ticker_received = True
            _mark_data(state)
        elif "lastUpdateId" in payload and "bids" in payload and "asks" in payload:
            state.order_book_snapshot_received = True
            state._snapshot_sequence = int(payload["lastUpdateId"])
            _mark_data(state)
        return

    if exchange_id == "okx":
        if payload.get("event") == "subscribe":
            state.subscription_ack = True
        arg = payload.get("arg")
        if not isinstance(arg, dict) or not payload.get("data"):
            return
        if arg.get("channel") == "tickers":
            state.ticker_received = True
            _mark_data(state)
        elif arg.get("channel") == "books":
            action = payload.get("action")
            book = payload["data"][0]
            if action == "snapshot":
                state.order_book_snapshot_received = True
                state._last_sequence = int(book["seqId"])
            elif action == "update":
                state.order_book_delta_received = True
                _check_sequence(state, int(book["seqId"]), int(book["prevSeqId"]))
            _mark_data(state)
        return

    if exchange_id == "bybit":
        if payload.get("op") == "subscribe" and payload.get("success") is True:
            state.subscription_ack = True
        if payload.get("op") in {"ping", "pong"} and payload.get("success") is True:
            state.heartbeat_ok = True
        topic = str(payload.get("topic", ""))
        if topic.startswith("tickers."):
            state.ticker_received = True
            _mark_data(state)
        elif topic.startswith("orderbook."):
            data = payload.get("data", {})
            if payload.get("type") == "snapshot":
                state.order_book_snapshot_received = True
                state._last_sequence = int(data["u"])
            elif payload.get("type") == "delta":
                state.order_book_delta_received = True
                _check_sequence(state, int(data["u"]))
            _mark_data(state)
        return

    if exchange_id == "kraken":
        if payload.get("method") == "subscribe" and payload.get("success") is True:
            state.subscription_ack = True
        channel = payload.get("channel")
        if channel == "ticker":
            state.ticker_received = True
            _mark_data(state)
        elif channel == "book":
            if payload.get("type") == "snapshot":
                state.order_book_snapshot_received = True
            elif payload.get("type") == "update":
                state.order_book_delta_received = True
            _mark_data(state)
        return

    if exchange_id == "coinbase":
        channel = payload.get("channel")
        if "sequence_num" in payload:
            _check_sequence(state, int(payload["sequence_num"]), contiguous=True)
        if channel == "subscriptions":
            state.subscription_ack = True
        elif channel == "heartbeats":
            state.heartbeat_ok = True
            _mark_data(state)
        elif channel == "ticker":
            state.ticker_received = True
            _mark_data(state)
        elif channel == "l2_data":
            events = payload.get("events", [])
            if any(event.get("type") == "snapshot" for event in events):
                state.order_book_snapshot_received = True
            if any(event.get("type") == "update" for event in events):
                state.order_book_delta_received = True
            _mark_data(state)


async def initialize_connection(
    websocket: ClientConnection, config: ExchangeConfig, state: ProbeState
) -> None:
    if config.exchange_id == "bitbank":
        opening = await asyncio.wait_for(websocket.recv(), timeout=5)
        if not isinstance(opening, str) or not opening.startswith("0"):
            raise ValueError("missing Socket.IO Engine.IO opening packet")
        await websocket.send("40")
        namespace_ack = await asyncio.wait_for(websocket.recv(), timeout=5)
        if not isinstance(namespace_ack, str) or not namespace_ack.startswith("40"):
            raise ValueError("missing Socket.IO namespace acknowledgement")
        for room in config.socket_io_rooms:
            await websocket.send("42" + json.dumps(["join-room", room], separators=(",", ":")))
        state.subscription_ack = True
    else:
        for subscription in config.subscriptions:
            await websocket.send(json.dumps(subscription, separators=(",", ":")))

    pong_waiter = await websocket.ping()
    await asyncio.wait_for(pong_waiter, timeout=5)
    state.heartbeat_ok = True


def handle_bitbank_message(raw: str, state: ProbeState) -> str | None:
    if raw == "2":
        return "3"
    if not raw.startswith("42"):
        return None
    payload = json.loads(raw[2:])
    if not isinstance(payload, list) or len(payload) != 2 or payload[0] != "message":
        return None
    body = payload[1]
    room = body.get("room_name", "")
    data = body.get("message", {}).get("data", {})
    if room.startswith("ticker_"):
        state.ticker_received = True
    elif room.startswith("depth_whole_"):
        state.order_book_snapshot_received = True
        state._snapshot_sequence = int(data["sequenceId"])
        state._last_sequence = state._snapshot_sequence
    elif room.startswith("depth_diff_"):
        state.order_book_delta_received = True
        _check_sequence(state, int(data["s"]))
    else:
        return None
    _mark_data(state)
    return None


def finalize_state(state: ProbeState, stale_after_seconds: float) -> None:
    state.completed_ts_ms = time.time_ns() // 1_000_000
    state.duration_ms = state.completed_ts_ms - state.started_ts_ms
    if state._last_data_monotonic_ns is not None:
        observed_end_ns = state._observation_ended_monotonic_ns or time.monotonic_ns()
        state.last_message_age_ms = (
            observed_end_ns - state._last_data_monotonic_ns
        ) // 1_000_000
        state.stale = state.last_message_age_ms > stale_after_seconds * 1000

    if not state.order_book_snapshot_received:
        state.synchronization_status = "UNSYNCED"
    elif (
        state.exchange_id in {"okx", "bybit", "coinbase", "bitbank"}
        and state.order_book_delta_received
        and state.sequence_checked
        and state.sequence_ok
    ):
        state.synchronization_status = "VERIFIED"
    elif state.order_book_delta_received:
        state.synchronization_status = "PARTIAL"
    else:
        state.synchronization_status = "SNAPSHOT_ONLY"

    state.success = all(
        (
            state.subscription_ack,
            state.heartbeat_ok,
            state.ticker_received,
            state.order_book_snapshot_received,
            state.order_book_delta_received,
            not state.stale,
            state.sequence_ok,
        )
    )


async def probe_exchange(
    config: ExchangeConfig, duration_seconds: float, stale_after_seconds: float
) -> ProbeState:
    state = ProbeState(config.exchange_id, time.time_ns() // 1_000_000)
    deadline = asyncio.get_running_loop().time() + duration_seconds
    for attempt in range(1, 3):
        state.connection_attempts = attempt
        try:
            async with connect(
                config.url,
                open_timeout=10,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=10,
                max_size=MAX_MESSAGE_BYTES,
            ) as websocket:
                await initialize_connection(websocket, config, state)
                while (remaining := deadline - asyncio.get_running_loop().time()) > 0:
                    try:
                        raw = await asyncio.wait_for(websocket.recv(), timeout=min(remaining, 2))
                    except TimeoutError:
                        continue
                    if not isinstance(raw, str):
                        continue
                    if config.exchange_id == "bitbank":
                        reply = handle_bitbank_message(raw, state)
                        if reply is not None:
                            await websocket.send(reply)
                    elif raw == "pong":
                        state.heartbeat_ok = True
                    else:
                        handle_json_message(config.exchange_id, json.loads(raw), state)
                state._observation_ended_monotonic_ns = time.monotonic_ns()
                break
        except (
            ImportError,
            OSError,
            TimeoutError,
            ValueError,
            json.JSONDecodeError,
            WebSocketException,
        ) as exc:
            state.error_type = type(exc).__name__
            state.error_message = str(exc)
            if attempt == 2 or asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(0.5)

    finalize_state(state, stale_after_seconds)
    return state


MAX_MESSAGE_BYTES: Final = 2_000_000


async def run_all(duration_seconds: float, stale_after_seconds: float) -> list[ProbeState]:
    async with asyncio.TaskGroup() as task_group:
        tasks = [
            task_group.create_task(
                probe_exchange(config, duration_seconds, stale_after_seconds)
            )
            for config in CONFIGS
        ]
    return [task.result() for task in tasks]


def default_output_path() -> Path:
    utc_now = datetime.now(UTC)
    return Path("data/probes") / f"{utc_now:%Y-%m-%d}" / f"websocket-{utc_now:%H%M%S}.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--stale-after", type=float, default=5.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.duration <= 0 or args.stale_after <= 0:
        parser.error("duration and stale threshold must be positive")

    results = asyncio.run(run_all(args.duration, args.stale_after))
    output_path = args.output or default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output:
        for result in results:
            output.write(json.dumps(result.public_dict(), separators=(",", ":")) + "\n")
            status = "PASS" if result.success else "FAIL"
            print(
                f"{status:4} {result.exchange_id:8} messages={result.message_count:<5} "
                f"ticker={result.ticker_received!s:<5} snapshot="
                f"{result.order_book_snapshot_received!s:<5} delta="
                f"{result.order_book_delta_received!s:<5} sync={result.synchronization_status}"
            )
    passed = sum(result.success for result in results)
    print(f"\n{passed}/{len(results)} probes succeeded; evidence: {output_path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
