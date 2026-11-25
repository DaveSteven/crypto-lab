#!/usr/bin/env python3
"""Capture live USDT tickers and record every directed cross-exchange spread."""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from decimal import Decimal
from itertools import permutations
from pathlib import Path

from crypto_lab.analysis import CostInputs, analyze_spread
from crypto_lab.market_data import normalize_ticker
from crypto_lab.market_data.live import TICKER_ENDPOINTS, fetch_json
from crypto_lab.models import DataQualityStatus


def optional_costs(args: argparse.Namespace) -> CostInputs | None:
    raw_rates = (
        args.assumed_buy_fee_rate,
        args.assumed_sell_fee_rate,
        args.assumed_execution_cost_rate,
        args.assumed_rebalance_cost_rate,
    )
    if all(value is None for value in raw_rates):
        return None
    if any(value is None for value in raw_rates):
        raise ValueError("all four assumed cost rates must be supplied together")
    return CostInputs(
        model_id="ASSUMED:CLI_V1",
        buy_fee_rate=Decimal(args.assumed_buy_fee_rate),
        sell_fee_rate=Decimal(args.assumed_sell_fee_rate),
        execution_cost_rate=Decimal(args.assumed_execution_cost_rate),
        rebalance_cost_rate=Decimal(args.assumed_rebalance_cost_rate),
        is_assumption=True,
    )


def default_output_path() -> Path:
    utc_now = datetime.now(UTC)
    return (
        Path("data/experiments")
        / f"{utc_now:%Y-%m-%d}"
        / f"spread-rest-{utc_now:%H%M%S}.jsonl"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--target-quantity", type=Decimal, default=None)
    parser.add_argument("--assumed-buy-fee-rate")
    parser.add_argument("--assumed-sell-fee-rate")
    parser.add_argument("--assumed-execution-cost-rate")
    parser.add_argument("--assumed-rebalance-cost-rate")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    try:
        costs = optional_costs(args)
    except (ValueError, ArithmeticError) as exc:
        parser.error(str(exc))

    tickers = []
    for endpoint in TICKER_ENDPOINTS:
        if endpoint.quote_asset != "USDT":
            continue
        raw, received_ts_ms = fetch_json(endpoint, args.timeout)
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

    observed_ts_ms = time.time_ns() // 1_000_000
    observations = [
        analyze_spread(
            buy,
            sell,
            observed_ts_ms,
            target_quantity=args.target_quantity,
            costs=costs,
        )
        for buy, sell in permutations(tickers, 2)
    ]
    output_path = args.output or default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output:
        for observation in observations:
            output.write(observation.model_dump_json() + "\n")

    valid = [item for item in observations if item.quality_status is DataQualityStatus.VALID]
    positive = [item for item in valid if item.gross_spread > 0]
    best = max(valid, key=lambda item: item.gross_spread_rate, default=None)
    print(f"recorded={len(observations)} valid={len(valid)} positive_gross={len(positive)}")
    if best is not None:
        print(
            f"largest gross spread: buy={best.buy_exchange_id.value} "
            f"sell={best.sell_exchange_id.value} rate={best.gross_spread_rate}"
        )
        if best.estimated_net_profit is None:
            print("net estimate: null (complete cost inputs were not supplied)")
    print(f"evidence: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
