#!/usr/bin/env python3
"""Fetch and normalize one live ticker from each Phase 0 exchange."""

from __future__ import annotations

import argparse
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

from crypto_lab.market_data import normalize_ticker
from crypto_lab.market_data.live import TICKER_ENDPOINTS, fetch_json


def default_output_path() -> Path:
    utc_now = datetime.now(UTC)
    return (
        Path("data/normalized")
        / f"{utc_now:%Y-%m-%d}"
        / f"ticker-rest-{utc_now:%H%M%S}.jsonl"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")

    output_path = args.output or default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    failures = 0
    for endpoint in TICKER_ENDPOINTS:
        try:
            raw, received_ts_ms = fetch_json(endpoint, args.timeout)
            record = normalize_ticker(
                endpoint.exchange_id,
                endpoint.base_asset,
                endpoint.quote_asset,
                raw,
                received_ts_ms,
                raw_ref=endpoint.url,
            )
            records.append(record)
            print(
                f"PASS {endpoint.exchange_id.value:8} {record.instrument_id:27} "
                f"quality={record.quality_status.value}"
            )
        except (KeyError, IndexError, TypeError, ValueError, urllib.error.URLError) as exc:
            failures += 1
            print(f"FAIL {endpoint.exchange_id.value:8} {type(exc).__name__}: {exc}")

    with output_path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(record.model_dump_json() + "\n")
    print(f"\n{len(records)}/{len(TICKER_ENDPOINTS)} normalized; evidence: {output_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
