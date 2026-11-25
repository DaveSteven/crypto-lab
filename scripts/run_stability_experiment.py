#!/usr/bin/env python3
"""Run a bounded repeated-REST market-data and spread stability experiment."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import time
import urllib.error
from datetime import UTC, datetime
from itertools import permutations
from pathlib import Path

from crypto_lab.analysis import analyze_spread
from crypto_lab.experiments.stability import (
    GrossSpreadEpisodes,
    RotatingJsonlWriter,
    StorageLimitReachedError,
)
from crypto_lab.market_data import normalize_ticker
from crypto_lab.market_data.live import TICKER_ENDPOINTS, fetch_json
from crypto_lab.models import DataQualityStatus

LOGGER = logging.getLogger("crypto_lab.stability")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=float, default=300)
    parser.add_argument("--interval-seconds", type=float, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=5)
    parser.add_argument("--rotate-mb", type=float, default=25)
    parser.add_argument("--max-storage-mb", type=float, default=512)
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    parser.add_argument("--output-directory", type=Path, default=None)
    args = parser.parse_args()
    if min(args.duration_seconds, args.interval_seconds, args.timeout_seconds) <= 0:
        parser.error("duration, interval, and timeout must be positive")
    if args.rotate_mb <= 0 or args.max_storage_mb < args.rotate_mb:
        parser.error("storage limits must satisfy 0 < rotate-mb <= max-storage-mb")
    return args


def default_directory(started: datetime) -> Path:
    experiment_id = f"stability-{started:%H%M%S-%f}"
    return Path("data/experiments") / f"{started:%Y-%m-%d}" / experiment_id


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    started_at = datetime.now(UTC)
    started_ts_ms = time.time_ns() // 1_000_000
    output_directory = args.output_directory or default_directory(started_at)
    stop_requested = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    endpoints = [item for item in TICKER_ENDPOINTS if item.quote_asset == "USDT"]
    deadline = time.monotonic() + args.duration_seconds
    next_cycle = time.monotonic()
    cycles_attempted = 0
    cycles_succeeded = 0
    request_attempts = 0
    request_successes = 0
    request_failures: dict[str, int] = {}
    observations_total = 0
    valid_observations = 0
    positive_gross_observations = 0
    net_positive_observations = 0
    safe_stop_reason: str | None = None
    episodes = GrossSpreadEpisodes(max_gap_ms=int(args.interval_seconds * 1_500))
    last_progress = time.monotonic()

    rotate_bytes = int(args.rotate_mb * 1024 * 1024)
    max_bytes = int(args.max_storage_mb * 1024 * 1024)
    writer = RotatingJsonlWriter(output_directory, "observations", rotate_bytes, max_bytes)
    try:
        while not stop_requested and time.monotonic() < deadline:
            cycles_attempted += 1
            tickers = []
            cycle_errors = []
            for endpoint in endpoints:
                request_attempts += 1
                try:
                    raw, received_ts_ms = fetch_json(endpoint, args.timeout_seconds)
                    tickers.append(
                        normalize_ticker(
                            endpoint.exchange_id,
                            endpoint.base_asset,
                            endpoint.quote_asset,
                            raw,
                            received_ts_ms,
                            raw_ref=endpoint.url,
                        )
                    )
                    request_successes += 1
                except (
                    KeyError,
                    IndexError,
                    TypeError,
                    ValueError,
                    TimeoutError,
                    urllib.error.URLError,
                ) as exc:
                    key = f"{endpoint.exchange_id.value}:{type(exc).__name__}"
                    request_failures[key] = request_failures.get(key, 0) + 1
                    cycle_errors.append(key)

            observed_ts_ms = time.time_ns() // 1_000_000
            observations = []
            if len(tickers) == len(endpoints):
                cycles_succeeded += 1
                observations = [
                    analyze_spread(buy, sell, observed_ts_ms)
                    for buy, sell in permutations(tickers, 2)
                ]
                episodes.observe(observations, observed_ts_ms)
                observations_total += len(observations)
                valid_observations += sum(
                    item.quality_status is DataQualityStatus.VALID for item in observations
                )
                positive_gross_observations += sum(
                    item.quality_status is DataQualityStatus.VALID and item.gross_spread > 0
                    for item in observations
                )
                net_positive_observations += sum(
                    item.estimated_net_profit is not None and item.estimated_net_profit > 0
                    for item in observations
                )

            writer.write(
                {
                    "record_type": "cycle",
                    "cycle": cycles_attempted,
                    "observed_ts_ms": observed_ts_ms,
                    "errors": cycle_errors,
                    "observations": [item.model_dump(mode="json") for item in observations],
                }
            )
            now = time.monotonic()
            if now - last_progress >= 60:
                LOGGER.info(
                    f"progress cycles={cycles_attempted} successful={cycles_succeeded} "
                    f"requests={request_successes}/{request_attempts} bytes={writer.total_bytes}"
                )
                last_progress = now
            next_cycle += args.interval_seconds
            sleep_seconds = next_cycle - time.monotonic()
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    except StorageLimitReachedError as exc:
        safe_stop_reason = str(exc)
    finally:
        writer.close()
        episodes.finish()

    completed_ts_ms = time.time_ns() // 1_000_000
    if stop_requested and safe_stop_reason is None:
        safe_stop_reason = "signal requested"
    summary = {
        "schema_version": "1.0.0",
        "started_ts_ms": started_ts_ms,
        "completed_ts_ms": completed_ts_ms,
        "configured_duration_seconds": args.duration_seconds,
        "actual_duration_seconds": (completed_ts_ms - started_ts_ms) / 1000,
        "interval_seconds": args.interval_seconds,
        "cycles_attempted": cycles_attempted,
        "cycles_succeeded": cycles_succeeded,
        "request_attempts": request_attempts,
        "request_successes": request_successes,
        "request_failures": request_failures,
        "observations_total": observations_total,
        "valid_observations": valid_observations,
        "positive_gross_observations": positive_gross_observations,
        "net_positive_observations": net_positive_observations,
        "positive_gross_episode_count": episodes.completed_count,
        "positive_gross_episode_duration_ms": episodes.completed_duration_ms,
        "bytes_written": writer.total_bytes,
        "files_written": writer.file_count,
        "safe_stop_reason": safe_stop_reason,
        "cost_model": None,
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    summary_path = output_directory / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    LOGGER.info("experiment summary: %s", json.dumps(summary, separators=(",", ":")))
    LOGGER.info("summary path: %s", summary_path)
    return 0 if safe_stop_reason is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
